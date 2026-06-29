# References

Primary references used to inform the architecture.

## Official Documentation

- FastAPI documentation: https://fastapi.tiangolo.com/
- PostgreSQL documentation: https://www.postgresql.org/docs/current/
- Temporal documentation: https://docs.temporal.io/
- Redpanda documentation: https://docs.redpanda.com/
- MinIO documentation: https://min.io/docs/minio/
- Keycloak documentation: https://www.keycloak.org/documentation
- Open Policy Agent documentation: https://www.openpolicyagent.org/docs/
- OpenTelemetry documentation: https://opentelemetry.io/docs/
- Prometheus documentation: https://prometheus.io/docs/
- Grafana documentation: https://grafana.com/docs/
- Qdrant documentation: https://qdrant.tech/documentation/
- DuckDB documentation: https://duckdb.org/docs/
- Polars documentation: https://docs.pola.rs/
- OpenSearch documentation: https://opensearch.org/docs/

## Local Project References

- Hugging Face MVP repo: `/home/sergiopesch/dedupe-acopiove`
- OpenClaw repo: `/home/sergiopesch/openclaw`
- OpenClaw state/config: `/home/sergiopesch/.openclaw`

## MVP Evidence

The MVP demonstrated:

- Full public API run above 100k records.
- SOS API throttling requirement.
- Persistent `/data` Hugging Face storage requirement.
- Need for staged image hashing and face-recognition jobs.
- Need for human review queues.
- Need for a production API and workflow layer separate from Gradio.

