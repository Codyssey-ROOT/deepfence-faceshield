import time

import requests


class ApiCallError(Exception):
    pass


class ApiClient:

    def __init__(self, settings):
        self.settings = settings
        self.session = requests.Session()

        self.headers = {
            "X-Internal-API-Key":
                settings.internal_api_key
        }

    def close(self):
        self.session.close()

    def _post(self, path, payload=None):
        url = self.settings.spring_base_url + path

        try:
            response = self.session.post(
                url,
                json=payload,
                headers=self.headers,
                timeout=(5, 30)
            )

        except requests.RequestException:
            raise ApiCallError(
                "Spring API 네트워크 요청 실패: "
                + path
            ) from None

        if response.status_code == 204:
            return None

        if response.status_code != 200:
            raise ApiCallError(
                "Spring API 요청 실패: {} HTTP {}".format(
                    path,
                    response.status_code
                )
            )

        try:
            body = response.json()
        except ValueError:
            raise ApiCallError(
                "Spring API 응답이 JSON이 아닙니다."
            ) from None

        if body.get("statusCode") != 200:
            raise ApiCallError(
                "Spring API에서 요청을 거부했습니다: "
                + path
            )

        return body.get("data")

    def claim_job(self):
        """
        대기 중인 FaceShield 작업 1개 할당
        """
        return self._post(
            "/faceshield/jobs/claim"
        )

    def download_image(self, download_url):
        """
        Presigned GET URL로 블러 이미지 다운로드
        """
        if not download_url.startswith("https://"):
            raise ApiCallError(
                "올바르지 않은 이미지 다운로드 URL"
            )

        max_size = self.settings.max_source_bytes

        try:
            with self.session.get(
                    download_url,
                    stream=True,
                    timeout=(5, 60)
            ) as response:

                if response.status_code != 200:
                    raise ApiCallError(
                        "S3 이미지 다운로드 실패: HTTP {}"
                        .format(response.status_code)
                    )

                chunks = []
                total_size = 0

                for chunk in response.iter_content(
                        chunk_size=64 * 1024
                ):
                    if not chunk:
                        continue

                    total_size += len(chunk)

                    if total_size > max_size:
                        raise ApiCallError(
                            "블러 이미지가 최대 크기를 초과했습니다."
                        )

                    chunks.append(chunk)

                data = b"".join(chunks)

        except requests.RequestException:
            raise ApiCallError(
                "S3 이미지 다운로드 네트워크 오류"
            ) from None

        if not data:
            raise ApiCallError(
                "다운로드한 이미지가 비어 있습니다."
            )

        return data

    def create_presigned_url(
            self,
            job_id,
            lease_token,
            image_size
    ):
        """
        보호 이미지 S3 업로드 URL 요청
        """
        return self._post(
            "/faceshield/images/presigned-url",
            {
                "jobId": job_id,
                "leaseToken": lease_token,
                "contentType": "image/png",
                "fileSize": image_size
            }
        )

    def upload_image(self, upload_url, image_data):
        """
        Presigned PUT URL로 보호 이미지 업로드
        """
        if not upload_url.startswith("https://"):
            raise ApiCallError(
                "올바르지 않은 이미지 업로드 URL"
            )

        if not image_data:
            raise ApiCallError(
                "업로드할 이미지가 비어 있습니다."
            )

        if len(image_data) > self.settings.max_result_bytes:
            raise ApiCallError(
                "보호 이미지가 최대 크기를 초과했습니다."
            )

        for attempt in range(3):

            try:
                response = self.session.put(
                    upload_url,
                    data=image_data,
                    headers={
                        "Content-Type": "image/png"
                    },
                    timeout=(5, 90)
                )

            except requests.RequestException:
                if attempt < 2:
                    time.sleep(attempt + 1)
                    continue

                raise ApiCallError(
                    "S3 이미지 업로드 네트워크 오류"
                ) from None

            if response.status_code in (200, 201, 204):
                return

            if response.status_code >= 500 and attempt < 2:
                time.sleep(attempt + 1)
                continue

            raise ApiCallError(
                "S3 이미지 업로드 실패: HTTP {}"
                .format(response.status_code)
            )

        raise ApiCallError(
            "S3 이미지 업로드 재시도 횟수 초과"
        )

    def complete_job(
            self,
            job_id,
            lease_token,
            object_key
    ):
        """
        Spring에 보호 이미지 업로드 완료 통보

        Spring 완료 API는 동일 요청의 재전송을 허용하므로
        일시적인 연결 실패에 대해 재시도한다.
        """
        payload = {
            "jobId": job_id,
            "leaseToken": lease_token,
            "objectKey": object_key
        }

        for attempt in range(3):
            try:
                self._post(
                    "/faceshield/images/complete",
                    payload
                )
                return

            except ApiCallError:
                if attempt == 2:
                    raise

                time.sleep(attempt + 1)

    def fail_job(
            self,
            job_id,
            lease_token,
            reason
    ):
        """
        Spring에 처리 실패 보고
        """
        self._post(
            "/faceshield/jobs/fail",
            {
                "jobId": job_id,
                "leaseToken": lease_token,
                "reason": reason[:300]
            }
        )
