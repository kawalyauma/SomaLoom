FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*
RUN groupadd --gid 10002 runner && useradd --uid 10002 --gid runner --create-home runner
WORKDIR /tmp
RUN curl -fsSL https://chatgpt.com/codex/install.sh -o /tmp/codex-install.sh && chmod 755 /tmp/codex-install.sh
RUN CODEX_HOME=/opt/codex-runtime CODEX_INSTALL_DIR=/opt/codex-bin CODEX_RELEASE=0.164.0 CODEX_NON_INTERACTIVE=true sh /tmp/codex-install.sh
COPY infra/codex/service.py /opt/codex-service.py
COPY infra/codex/error_codes.py /opt/error_codes.py
RUN chmod 555 /opt/codex-service.py
USER 10002:10002
ENV HOME=/home/runner CODEX_HOME=/home/runner/.codex PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8090
CMD ["python3", "/opt/codex-service.py"]
