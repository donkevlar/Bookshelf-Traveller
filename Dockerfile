# official Python runtime as a base image
FROM python:3.12.1-slim-bookworm

# Set the working directory
WORKDIR /ABSBOT

# Copy the current directory contents
COPY Scripts/ /ABSBOT


# Install any needed packages specified in requirements.txt
RUN pip install discord.py-interactions[voice]
RUN pip install --trusted-host pypi.python.org -r requirements.txt


RUN set -ex \
    && apt-get update \
    && apt-get install -y ffmpeg \
    && apt-get install -y libffi-dev libnacl-dev \
    && apt-get upgrade -y \
    && apt-get autoremove -y \
    && apt-get clean -y

# Health check
HEALTHCHECK --interval=1m --timeout=10s --retries=1 \
  CMD python3 healthcheck.py


CMD ["python", "main.py"]
