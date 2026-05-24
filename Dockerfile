ARG BUILD_FROM
FROM $BUILD_FROM

# Install dependencies and Python packages
RUN apk add --no-cache python3 py3-pip jq udev \
    && pip3 install --no-cache-dir --break-system-packages pyserial paho-mqtt

# Set work directory
WORKDIR /usr/src/app

# Copy files
COPY main.py .
COPY run.sh .

# Make scripts executable
RUN chmod a+x run.sh

# Run script
CMD [ "./run.sh" ]
