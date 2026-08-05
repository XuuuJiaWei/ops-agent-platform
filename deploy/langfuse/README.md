# Local Langfuse

This directory runs a self-hosted Langfuse v4 stack for local development with Docker Compose.

## Start

```bash
cd deploy/langfuse
docker compose --env-file .env up -d
docker compose ps
```

Open Langfuse at http://localhost:3001.

## Ops Agent Configuration

After creating a Langfuse project in the UI, copy the project API keys into the repository root `.env`:

```bash
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```

Keep `config/config.yaml` pointed at the local server:

```yaml
langfuse:
  base_url: http://localhost:3001
```

## Useful Commands

```bash
cd deploy/langfuse
docker compose logs -f langfuse-web langfuse-worker
docker compose down
docker compose down -v
```

Use `docker compose down -v` only when you want to delete the local Langfuse data volumes.

## Docker Hub Mirror Fallback

If Docker Hub direct pulls fail, pull through a mirror and tag images back to the official names used by Compose:

```bash
docker pull docker.1panel.live/library/postgres:16-alpine && docker tag docker.1panel.live/library/postgres:16-alpine postgres:16-alpine
docker pull docker.1panel.live/library/redis:7-alpine && docker tag docker.1panel.live/library/redis:7-alpine redis:7-alpine
docker pull docker.1panel.live/minio/minio:latest && docker tag docker.1panel.live/minio/minio:latest minio/minio:latest
docker pull docker.1panel.live/clickhouse/clickhouse-server:25.12 && docker tag docker.1panel.live/clickhouse/clickhouse-server:25.12 clickhouse/clickhouse-server:25.12
docker pull docker.1panel.live/langfuse/langfuse:4 && docker tag docker.1panel.live/langfuse/langfuse:4 langfuse/langfuse:4
docker pull docker.1panel.live/langfuse/langfuse-worker:4 && docker tag docker.1panel.live/langfuse/langfuse-worker:4 langfuse/langfuse-worker:4
```
