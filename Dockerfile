FROM python:3.12-slim

# Use /app as the common project root inside the image.
WORKDIR /app

# Keep the runtime image small while still supporting packages that need a compiler.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install only the dependencies needed by the MES and Shopfloor MCP runtimes.
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# One image contains both server-side Shopfloor components.
COPY MES /app/MES
COPY MCP /app/MCP
COPY docker/shopfloor-entrypoint.sh /usr/local/bin/shopfloor-entrypoint

# Keep the static repair notebook outside the persistent data mount so a new
# empty host volume can be seeded without baking mutable MES history into it.
RUN mkdir -p /opt/shopfloor-seed \
    && cp /app/MES/data/error_notebook.json /opt/shopfloor-seed/error_notebook.json \
    && chmod +x /usr/local/bin/shopfloor-entrypoint

ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# MES Streamlit runtime.
ENV STREAMLIT_SERVER_PORT=8501
EXPOSE 8501

# Shopfloor MCP runtime.
ENV SHOPFLOOR_MCP_HOST=0.0.0.0
ENV SHOPFLOOR_MCP_PORT=8001
EXPOSE 8001

ENTRYPOINT ["shopfloor-entrypoint"]
CMD ["mes"]
