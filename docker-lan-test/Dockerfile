# v2.20 LAN-only testing image. The vendor wheel set is Python 3.13 / Linux AMD64.
FROM python:3.13-slim-bookworm
ARG TARGETARCH
RUN set -eu; test "${TARGETARCH:-amd64}" = amd64; \
    groupadd --system --gid 10001 ryoiku; \
    useradd --system --no-create-home --uid 10001 --gid 10001 ryoiku; \
    mkdir -p /opt/ryoiku/app/static /opt/ryoiku/vendor /opt/ryoiku/runtime /data; \
    chown 10001:10001 /data
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/ryoiku/app:/opt/ryoiku/vendor:/opt/ryoiku/runtime \
    RYOIKU_DATA_DIR=/data
WORKDIR /opt/ryoiku/app
COPY --chown=10001:10001 upload_to_domain_root/_private/vendor/ /opt/ryoiku/vendor/
COPY --chown=10001:10001 upload_to_domain_root/_private/app/ /opt/ryoiku/app/
# The domain-root stylesheet/script are NOT copied by Lolipop into app/static.
COPY --chown=10001:10001 upload_to_domain_root/static/day_flow_multi.css upload_to_domain_root/static/day_flow_multi.js /opt/ryoiku/app/static/
COPY --chown=10001:10001 docker/server.py /opt/ryoiku/runtime/server.py
RUN pip install --no-cache-dir 'uvicorn==0.48.0' && \
    chmod -R a+rX /opt/ryoiku/app /opt/ryoiku/vendor /opt/ryoiku/runtime && \
    chmod 0755 /opt/ryoiku/app /opt/ryoiku/runtime && \
    python3 -c 'import uvicorn,fastapi,cryptography,argon2,pypdf,reportlab,docx,xlsxwriter; print("v2.20 dependencies OK")'
USER 10001:10001
# No EXPOSE instruction. Only the explicitly configured LAN IPv4 is used.
CMD ["python3", "/opt/ryoiku/runtime/server.py"]