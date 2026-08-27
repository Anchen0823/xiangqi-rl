#include <cuda_runtime.h>

#include <cmath>
#include <iostream>
#include <vector>

__global__ void saxpy(const float* x, float* y, float scale, int count) {
    const int index = blockIdx.x * blockDim.x + threadIdx.x;
    if (index < count) y[index] = scale * x[index] + y[index];
}

int main() {
    int count = 0;
    if (cudaGetDeviceCount(&count) != cudaSuccess || count < 1) return 2;
    cudaDeviceProp props{};
    if (cudaGetDeviceProperties(&props, 0) != cudaSuccess) return 3;
    constexpr int size = 4096;
    std::vector<float> x(size, 2.0F), y(size, 1.0F);
    float *deviceX = nullptr, *deviceY = nullptr;
    if (cudaMalloc(&deviceX, sizeof(float) * size) != cudaSuccess) return 4;
    if (cudaMalloc(&deviceY, sizeof(float) * size) != cudaSuccess) return 5;
    cudaMemcpy(deviceX, x.data(), sizeof(float) * size, cudaMemcpyHostToDevice);
    cudaMemcpy(deviceY, y.data(), sizeof(float) * size, cudaMemcpyHostToDevice);
    saxpy<<<(size + 255) / 256, 256>>>(deviceX, deviceY, 3.0F, size);
    if (cudaDeviceSynchronize() != cudaSuccess) return 6;
    cudaMemcpy(y.data(), deviceY, sizeof(float) * size, cudaMemcpyDeviceToHost);
    cudaFree(deviceX); cudaFree(deviceY);
    for (float value : y) if (std::abs(value - 7.0F) > 1e-5F) return 7;
    std::cout << "CUDA device: " << props.name << "\ncompute capability: "
              << props.major << '.' << props.minor << "\nVRAM bytes: " << props.totalGlobalMem
              << "\nResult = PASS\n";
    return 0;
}
