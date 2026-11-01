import argparse
import fcntl
import logging
import time

from app.config import Settings
from app.api_client import ApiClient, ApiCallError
from app.processor import FaceShieldProcessor

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s [%(levelname)s] "
        "%(message)s"
    )
)

logger = logging.getLogger(__name__)


class FaceShieldWorker:

    def __init__(self, settings):
        self.settings = settings

        self.api = ApiClient(settings)
        self.processor = FaceShieldProcessor(settings)

    def close(self):
        self.api.close()

    def run_once(self):
        """
        Spring에서 작업 하나를 받아 처리한다.

        반환:
            True  : 작업을 할당받음
            False : 대기 중인 작업 없음
        """
        job = self.api.claim_job()

        if job is None:
            logger.info("대기 중인 FaceShield 작업 없음")
            return False

        job_id = job["jobId"]
        lease_token = job["leaseToken"]

        logger.info(
            "FaceShield 작업 할당 jobId=%s",
            job_id
        )

        # 실제 Spring의 Lease 유효시간보다
        # 모델 실행 제한 시간이 짧아야 한다.
        lease_seconds = int(job["leaseSeconds"])

        timeout_seconds = min(
            self.settings.process_timeout_seconds,
            lease_seconds - 120
        )

        try:
            if timeout_seconds <= 0:
                raise RuntimeError(
                    "FaceShield 작업 Lease가 너무 짧습니다."
                )

            # 1. S3 블러 이미지 다운로드
            image_data = self.api.download_image(
                job["downloadUrl"]
            )

            logger.info(
                "블러 이미지 다운로드 완료 jobId=%s size=%s",
                job_id,
                len(image_data)
            )

            # 2. FaceShield 모델 실행
            logger.info(
                "FaceShield 모델 실행 시작 jobId=%s",
                job_id
            )

            protected_image = self.processor.process(
                job_id=job_id,
                image_data=image_data,
                timeout_seconds=timeout_seconds
            )

            logger.info(
                "FaceShield 모델 실행 완료 jobId=%s size=%s",
                job_id,
                len(protected_image)
            )

            # 3. Spring Presigned PUT URL 발급
            result = self.api.create_presigned_url(
                job_id=job_id,
                lease_token=lease_token,
                image_size=len(protected_image)
            )

            # 4. S3에 보호 이미지 업로드
            self.api.upload_image(
                result["uploadUrl"],
                protected_image
            )

            logger.info(
                "S3 보호 이미지 업로드 완료 jobId=%s",
                job_id
            )

        except Exception:
            logger.exception(
                "FaceShield 이미지 처리 실패 jobId=%s",
                job_id
            )

            # 완료 콜백 전 실패는 재시도 대상으로 보고
            try:
                self.api.fail_job(
                    job_id=job_id,
                    lease_token=lease_token,
                    reason="faceshield-processing-failed"
                )

            except ApiCallError as error:
                logger.error(
                    "작업 실패 콜백 전송 실패 jobId=%s error=%s",
                    job_id,
                    error
                )

            return True

        # 5. Spring 최종 완료 콜백
        try:
            self.api.complete_job(
                job_id=job_id,
                lease_token=lease_token,
                object_key=result["objectKey"]
            )

            logger.info(
                "FaceShield 최종 처리 완료 jobId=%s",
                job_id
            )

        except ApiCallError as error:
            # 완료 요청의 응답만 유실되었을 수도 있으므로
            # 즉시 fail 처리하지 않고 Lease 만료 후 복구
            logger.error(
                "완료 콜백 확인 실패 jobId=%s error=%s",
                job_id,
                error
            )

        return True

    def run(self):
        """
        계속해서 작업 조회 및 처리
        """
        logger.info("DeepFence FaceShield Worker 시작")

        while True:
            try:
                claimed = self.run_once()

                if not claimed:
                    time.sleep(
                        self.settings.poll_seconds
                    )

            except ApiCallError as error:
                logger.error(
                    "Spring API 연결 실패: %s",
                    error
                )

                time.sleep(
                    self.settings.poll_seconds
                )

            except Exception:
                logger.exception(
                    "Worker 예상하지 못한 오류"
                )

                time.sleep(
                    self.settings.poll_seconds
                )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--once",
        action="store_true",
        help="작업을 최대 1건 처리하고 종료"
    )

    args = parser.parse_args()

    settings = Settings.from_env()

    # 기존 FaceShield 실행 경로는 고정되어 있으므로
    # 동시에 두 개의 Worker가 실행되지 않도록 방지
    lock_path = (
            settings.model_dir / ".deepfence-worker.lock"
    )

    with open(lock_path, "a+") as lock_file:
        try:
            fcntl.flock(
                lock_file.fileno(),
                fcntl.LOCK_EX | fcntl.LOCK_NB
            )

        except BlockingIOError:
            raise SystemExit(
                "FaceShield Worker가 이미 실행 중입니다."
            )

        worker = FaceShieldWorker(settings)

        try:
            if args.once:
                worker.run_once()
            else:
                worker.run()

        except KeyboardInterrupt:
            logger.info("Worker 종료 요청")

        finally:
            worker.close()


if __name__ == "__main__":
    main()
