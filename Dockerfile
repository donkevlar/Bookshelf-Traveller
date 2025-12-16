# Use the official Python runtime as a base image
FROM python:3.13-slim-bookworm

# Set the working directory inside the container
WORKDIR /ABSBOT

# Copy requirements file
COPY Scripts/requirements.txt /ABSBOT/requirements.txt

# Install needed packages specified in requirements.txt
RUN pip install discord.py-interactions[voice] \
    && pip install --trusted-host pypi.python.org -r requirements.txt

# Install dependencies (ffmpeg, libffi, etc.)
RUN set -ex \
    && apt-get update \
    && apt-get install -y ffmpeg libffi-dev libnacl-dev \
    && apt-get upgrade -y \
    && apt-get autoremove -y \
    && apt-get clean -y \
    && rm -rf /var/lib/apt/lists/*

# Copy the rest of the application code
COPY Scripts/ /ABSBOT

# Expose web UI port
EXPOSE 12359

# Health check (now includes web UI check)
HEALTHCHECK --interval=1m --timeout=10s --retries=1 \
  CMD python3 healthcheck.py || exit 1

# Environment variables for configuration
ENV WEBUI_ENABLED=true
ENV WEBUI_HOST=0.0.0.0
ENV WEBUI_PORT=12359
ENV BOT_ENABLED=true

# Set the default command to use the launcher
CMD ["python", "launcher.py"]
