# n8n for Render (render.yaml -> paypilot-n8n). Docker Compose does not use this file:
# it runs the stock n8n image and imports workflows with the n8n-build / n8n-import
# services instead.
#
# Stage 1 renders the workflows with placeholders for the three values that only exist
# on the running service (secret, backend URL, merchant id). Stage 2 is the stock n8n
# image plus those templates; n8n/render-start.sh fills them in at boot.
# The stage-1 image has Python so the n8n image does not need a package manager.

FROM python:3.12-slim AS workflows
WORKDIR /src
COPY build_workflows.py ./
COPY lib ./lib
RUN N8N_WEBHOOK_SECRET=__PGA_SECRET__ \
    N8N_BACKEND_URL_FOR_N8N=__PGA_BACKEND_URL__ \
    PGA_MERCHANT_ID=__PGA_MERCHANT_ID__ \
    python build_workflows.py /out

FROM n8nio/n8n:2.46.5
COPY --from=workflows --chown=node:node /out /pga/workflows
COPY --chown=node:node render-workflows.js render-start.sh /pga/
ENV NODE_ENV=production
# Keep the default init (tini); only the command it runs changes.
ENTRYPOINT ["tini", "--", "/bin/sh", "/pga/render-start.sh"]
