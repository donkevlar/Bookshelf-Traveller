# official Python runtime as a base image
FROM python:3.12-slim

# Use an official MongoDB runtime as a base image
# FROM mongo:latest

# Set the working directory to /AudiblePy
WORKDIR /ABSBOT

# Copy the current directory contents into the container at /app
COPY Scripts/main.py /ABSBOT
COPY Scripts/bookshelfAPI.py /ABSBOT
COPY Scripts/requirements.txt /ABSBOT
COPY Scripts/settings.py /ABSBOT

# Install any needed packages specified in requirements.txt
RUN pip install --trusted-host pypi.python.org -r requirements.txt

RUN sudo apt install ffmpeg libffi-dev libnacl-dev -y

RUN set -ex \
    && apt-get update \
    && apt-get upgrade -y \
    && apt-get autoremove -y \
    && apt-get clean -y \
    && rm -rf /var/lib/apt/lists/*



CMD ["python", "main.py"]
