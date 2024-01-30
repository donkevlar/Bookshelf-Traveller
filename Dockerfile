# official Python runtime as a base image
FROM python:latest

# Use an official MongoDB runtime as a base image
# FROM mongo:latest

# Set the working directory to /AudiblePy
WORKDIR /ABSBOT

# Copy the current directory contents into the container at /app
COPY Scripts/main.py /ABSBOT
COPY Scripts/Bookshelf.py /ABSBOT
COPY Scripts/requirements.txt /ABSBOT

# Install any needed packages specified in requirements.txt
# RUN apt-get update && apt-get install -y python3-pip
RUN pip install --trusted-host pypi.python.org -r requirements.txt

CMD ["python", "main.py"]
