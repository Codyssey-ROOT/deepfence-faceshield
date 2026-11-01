# DeepFence GPU Server

사진 속 얼굴에 **사람 눈에는 거의 보이지 않는 보호 노이즈(적대적 섭동)를 입혀, 딥페이크 생성 모델이 얼굴을 제대로 학습·합성하지 못하게 만드는** DeepFence의 FaceShield 처리 서버입니다.

[블러 서버](https://github.com/Codyssey-ROOT/deepfence-blur)에서 개인정보가 가려진 이미지를 받아 얼굴 보호까지 마친 최종 이미지를 만듭니다.

- 서비스 전체 소개: [Codyssey-ROOT](https://github.com/Codyssey-ROOT)

## 기술 개요

### FaceShield란

딥페이크는 공개된 얼굴 사진을 입력으로 받아 다른 얼굴이나 장면에 합성합니다. FaceShield는 원본 사진에 미세한 노이즈를 더해, 사람이 보기에는 거의 같은 사진이지만 **AI 모델이 얼굴 특징을 잘못 인식하도록** 만드는 방어 기법입니다. 보호된 사진으로 딥페이크를 시도하면 결과물이 깨지거나 원래 얼굴과 다르게 생성됩니다.

<!-- TODO: 사용한 FaceShield 모델의 원본 저장소·논문 링크와 라이선스를 기입해 주세요 -->

### 처리 흐름

```
작업 요청(Claim) → 블러 이미지 다운로드 → FaceShield 모델 실행 → 결과 검증 → S3 업로드 → 완료 통보
```

1. Spring API 서버에 대기 중인 작업을 요청합니다. (`POST /faceshield/jobs/claim`)
2. 작업에 포함된 Presigned GET URL로 블러 처리된 이미지를 내려받습니다.
3. 이미지를 모델 입력 형식(PNG)으로 변환한 뒤 GPU에서 FaceShield 모델을 실행합니다.
4. 생성된 보호 이미지를 검증하고, 발급받은 Presigned PUT URL로 S3에 업로드합니다.
5. 완료(`/faceshield/images/complete`) 또는 실패(`/faceshield/jobs/fail`)를 Spring에 통보합니다.

### 안정성

- **Pull 방식 워커**: GPU 서버가 작업을 직접 가져가므로 외부에서 GPU 서버로 들어오는 포트를 열 필요가 없습니다.
- **Lease 기반 할당**: Spring이 발급한 임대 시간 안에 모델 실행이 끝나도록 제한 시간을 설정하고, 시간을 넘기면 모델 프로세스를 정리합니다.
- **단일 실행 보장**: 잠금 파일로 같은 모델 디렉터리에서 워커가 동시에 두 개 실행되지 않도록 막습니다.
- **재시도**: 업로드와 완료 통보는 일시적인 네트워크 오류에 대해 재시도합니다.

## 기술 스택

| 구분 | 기술 |
| --- | --- |
| 언어 | Python |
| 모델 실행 | FaceShield (GPU) |
| 이미지 처리 | Pillow |
| 외부 연동 | requests (Spring API, S3 Presigned URL) |
| 설정 | python-dotenv |

## 실행 방법

### 환경 변수

`.env.example`을 복사해 `.env`를 작성합니다.

| 변수 | 설명 |
| --- | --- |
| `SPRING_BASE_URL` | Spring API 서버 주소 |
| `FACESHIELD_INTERNAL_API_KEY` | Spring 내부 API 인증 키 |
| `FACESHIELD_MODEL_DIR` | FaceShield 모델 디렉터리 (`run.sh` 위치) |
| `FACESHIELD_INPUT_PATH`, `FACESHIELD_OUTPUT_PATH` | 모델 입력·출력 파일 경로 (모델 디렉터리 기준) |
| `POLL_SECONDS` | 대기 작업이 없을 때 다시 요청하기까지의 간격 |
| `PROCESS_TIMEOUT_SECONDS` | 모델 실행 제한 시간 |

### 실행

```bash
pip install -r requirements.txt

# 계속 작업을 받아 처리
python -m app.worker

# 작업을 최대 1건만 처리하고 종료
python -m app.worker --once
```

## 외부 자원 활용 내역

| 구분 | 명칭 | 용도 | 라이선스 |
| --- | --- | --- | --- |
| 모델 | FaceShield | 얼굴 딥페이크 방어 노이즈 생성 | 원본 저장소 라이선스 참고 |
| 오픈소스 | Pillow | 이미지 변환 | HPND |
| 오픈소스 | requests | HTTP 통신 | Apache 2.0 |
| 오픈소스 | python-dotenv | 환경 변수 로드 | BSD-3-Clause |
| 외부 서비스 | AWS S3 | 이미지 다운로드·업로드 | 상용 |
