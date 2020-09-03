FROM geki/colmap
# geki/colmap is based on nvidia/cuda:10.1-devel-ubuntu18.04

ARG USER_NAME=romi
ARG USER_ID=1000
ARG GROUP_ID=1000

USER root
RUN apt-get update && apt-get install -y \
    python3.7 python3.7-dev python3-pip wget && \
    update-alternatives --install /usr/bin/python python /usr/bin/python3.7 10 && \
    apt-get update && apt-get install -y --no-install-recommends \
    ocl-icd-libopencl1 opencl-headers clinfo && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    ln -s /usr/lib/x86_64-linux-gnu/libOpenCL.so.1 /usr/lib/libOpenCL.so && \
    # Create a non-root user and give it rights over its "home folder"
    addgroup --gid $GROUP_ID $USER_NAME && \
    adduser --disabled-password --gecos '' --uid $USER_ID --gid $GROUP_ID $USER_NAME && \
    chown -R ${USER_NAME}: /home/${USER_NAME}

# Change to non-root user:
USER ${USER_NAME}
# Change working directory:
WORKDIR /home/${USER_NAME}

RUN git clone https://github.com/inducer/pyopencl && \
    cd pyopencl/ && \
    git submodule update --init && \
    python -m pip install pybind11 --no-cache-dir && \
    ./configure.py --cl-pretend-version=1.2 && \
    python -m pip install . --no-cache-dir

USER root
RUN mkdir -p /etc/OpenCL/vendors && \
    echo "libnvidia-opencl.so.1" > /etc/OpenCL/vendors/nvidia.icd

USER ${USER_NAME}
# nvidia-container-runtime
ENV NVIDIA_VISIBLE_DEVICES all
ENV NVIDIA_DRIVER_CAPABILITIES compute,utility