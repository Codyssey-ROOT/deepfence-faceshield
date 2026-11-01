import os
import shutil
import signal
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

from PIL import Image


class FaceShieldProcessor:

    def __init__(self, settings):
        self.settings = settings

        self.model_dir = settings.model_dir
        self.input_path = settings.input_path
        self.output_path = settings.output_path

        self.log_dir = (
                Path(__file__).resolve().parent.parent / "logs"
        )

        self.log_dir.mkdir(
            parents=True,
            exist_ok=True
        )

    def _run_model(self, log_path, timeout_seconds):
        """
        기존 FaceShield run.sh 실행
        """
        with open(log_path, "wb") as log_file:

            process = subprocess.Popen(
                ["sh", "run.sh"],
                cwd=str(self.model_dir),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True
            )

            try:
                return_code = process.wait(
                    timeout=timeout_seconds
                )

            except BaseException:
                # Timeout 또는 Worker 종료 시
                # 모델의 자식 프로세스까지 함께 정리
                try:
                    os.killpg(
                        process.pid,
                        signal.SIGTERM
                    )
                except ProcessLookupError:
                    pass

                try:
                    process.wait(timeout=10)

                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(
                            process.pid,
                            signal.SIGKILL
                        )
                    except ProcessLookupError:
                        pass

                    process.wait()

                raise

            if return_code != 0:
                raise RuntimeError(
                    "FaceShield 실행 실패 (exit={})"
                    .format(return_code)
                )

    def process(
            self,
            job_id,
            image_data,
            timeout_seconds
    ):
        """
        1. 기존 입력 파일 백업
        2. 블러 이미지 -> PNG 변환
        3. FaceShield 모델 실행
        4. protected.png 검증
        5. 원본 테스트 파일 복원

        반환: 보호 이미지 PNG bytes
        """
        self.input_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        log_path = (
                self.log_dir / "job-{}.log".format(job_id)
        )

        with tempfile.TemporaryDirectory() as temp_dir:

            backup_path = (
                    Path(temp_dir) / "original_input.png"
            )

            had_original = self.input_path.exists()

            if had_original:
                shutil.copy2(
                    self.input_path,
                    backup_path
                )

            try:
                # 다운로드한 JPEG를 모델 입력용 PNG로 변환
                with Image.open(BytesIO(image_data)) as image:
                    image.load()

                    rgb_image = image.convert("RGB")

                    temp_input = (
                            Path(temp_dir) / "input.png"
                    )

                    rgb_image.save(
                        temp_input,
                        format="PNG"
                    )

                shutil.copy2(
                    temp_input,
                    self.input_path
                )

                # 이전 실행 결과 제거
                if self.output_path.exists():
                    self.output_path.unlink()

                # 기존 FaceShield 실행
                self._run_model(
                    log_path,
                    timeout_seconds
                )

                if not self.output_path.is_file():
                    raise RuntimeError(
                        "FaceShield 보호 이미지가 생성되지 않았습니다."
                    )

                # 이미지 형식 검증
                with Image.open(self.output_path) as result:
                    if result.format != "PNG":
                        raise RuntimeError(
                            "FaceShield 출력이 PNG가 아닙니다."
                        )

                    result.verify()

                result_size = self.output_path.stat().st_size

                if result_size <= 0:
                    raise RuntimeError(
                        "FaceShield 출력 이미지가 비어 있습니다."
                    )

                if result_size > self.settings.max_result_bytes:
                    raise RuntimeError(
                        "FaceShield 출력 이미지가 10MB를 초과했습니다."
                    )

                return self.output_path.read_bytes()

            finally:
                # GPU 서버의 원래 테스트 입력 복원
                if had_original:
                    shutil.copy2(
                        backup_path,
                        self.input_path
                    )

                elif self.input_path.exists():
                    self.input_path.unlink()
