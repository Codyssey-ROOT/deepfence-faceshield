import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent

load_dotenv(ROOT_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    spring_base_url: str
    internal_api_key: str

    model_dir: Path
    input_path: Path
    output_path: Path

    poll_seconds: int
    process_timeout_seconds: int

    max_source_bytes: int
    max_result_bytes: int

    @classmethod
    def from_env(cls):
        spring_url = os.getenv(
            "SPRING_BASE_URL", ""
        ).strip().rstrip("/")

        api_key = os.getenv(
            "FACESHIELD_INTERNAL_API_KEY", ""
        ).strip()

        model_dir = Path(
            os.getenv(
                "FACESHIELD_MODEL_DIR",
                "/home1/ncloud/iccv25_faceshield"
            )
        ).expanduser().resolve()

        input_path = model_dir / os.getenv(
            "FACESHIELD_INPUT_PATH",
            "data/test/image.png"
        )

        output_path = model_dir / os.getenv(
            "FACESHIELD_OUTPUT_PATH",
            "results/total_iter30/step_size1.0/"
            "noise_clamp12/[image]/protected.png"
        )

        if not spring_url.startswith("https://"):
            raise ValueError(
                "SPRING_BASE_URL은 HTTPS 주소여야 합니다."
            )

        if not api_key:
            raise ValueError(
                "FACESHIELD_INTERNAL_API_KEY가 필요합니다."
            )

        if not (model_dir / "run.sh").is_file():
            raise FileNotFoundError(
                "FaceShield run.sh를 찾을 수 없습니다."
            )

        settings = cls(
            spring_base_url=spring_url,
            internal_api_key=api_key,
            model_dir=model_dir,
            input_path=input_path,
            output_path=output_path,
            poll_seconds=int(
                os.getenv("POLL_SECONDS", "5")
            ),
            process_timeout_seconds=int(
                os.getenv(
                    "PROCESS_TIMEOUT_SECONDS",
                    "1500"
                )
            ),
            max_source_bytes=12 * 1024 * 1024,
            max_result_bytes=10 * 1024 * 1024
        )

        if settings.poll_seconds <= 0:
            raise ValueError(
                "POLL_SECONDS는 양수여야 합니다."
            )

        if settings.process_timeout_seconds <= 0:
            raise ValueError(
                "PROCESS_TIMEOUT_SECONDS는 양수여야 합니다."
            )

        return settings
