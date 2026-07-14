FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# FastMCP 3.4.3+ 는 Host/Origin 검증(DNS 리바인딩 보호)이 기본 ON 이라
# 프록시(카카오/Caddy)가 넘긴 Host 를 거부해 421 Misdirected Request 로 죽는다.
# 이 서버는 프록시 뒤 공개 서버-투-서버 MCP 라 해당 위협모델이 아니므로 끈다.
# (compose 의 env 는 Git 소스 등록 빌드엔 적용 안 되므로 이미지에 직접 박음)
ENV FASTMCP_HTTP_HOST_ORIGIN_PROTECTION=false

EXPOSE 8000

CMD ["python", "server.py"]
