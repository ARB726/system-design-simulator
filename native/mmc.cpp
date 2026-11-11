// Standalone C++17 M/M/c FCFS event kernel. No Python ABI or third-party libraries.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <functional>
#include <iomanip>
#include <iostream>
#include <queue>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

constexpr std::uint64_t max_requests = 2000000;

double real(const char* text) {
    std::size_t used = 0;
    const std::string value(text);
    double result = std::stod(value, &used);
    if (used != value.size() || !std::isfinite(result)) throw std::invalid_argument("Invalid numeric argument");
    return result;
}

struct Kernel {
    std::priority_queue<double, std::vector<double>, std::greater<double>> available;
    double warmup, previous = -1, response = 0, wait = 0;
    std::uint64_t arrivals = 0, measured = 0;
    Kernel(double servers, double warm) : warmup(warm) {
        if (servers < 1 || servers > 4096 || std::floor(servers) != servers || warm < 0)
            throw std::invalid_argument("Invalid servers or warmup");
        for (int i = 0; i < static_cast<int>(servers); ++i) available.push(0);
    }
    void arrival(double at, double service) {
        if (!std::isfinite(at) || !std::isfinite(service) || at < previous || at < 0 || service <= 0)
            throw std::invalid_argument("Invalid or unsorted request trace");
        if (++arrivals > max_requests) throw std::runtime_error("Native arrival limit reached");
        previous = at;
        double start = std::max(at, available.top());
        if (!std::isfinite(start + service)) throw std::invalid_argument("Trace time overflow");
        available.pop();
        available.push(start + service);
        if (at >= warmup) {
            ++measured;
            wait += start - at;
            response += start + service - at;
            if (!std::isfinite(response) || !std::isfinite(wait)) throw std::invalid_argument("Trace sum overflow");
        }
    }
    void print() const {
        if (!measured) throw std::invalid_argument("No requests in the measurement window");
        std::cout << std::setprecision(17) << "{\"requests\":" << measured
                  << ",\"mean_response_s\":" << response / measured
                  << ",\"mean_wait_s\":" << wait / measured << "}\n";
    }
};

int main(int argc, char** argv) {
    try {
        if (argc == 4 && std::string(argv[1]) == "--trace") {
            Kernel kernel(real(argv[2]), real(argv[3]));
            double at, service;
            while (std::cin >> at) {
                if (!(std::cin >> service)) throw std::invalid_argument("Incomplete trace row");
                kernel.arrival(at, service);
            }
            if (!std::cin.eof()) throw std::invalid_argument("Malformed trace");
            kernel.print();
        } else if (argc == 7) {
            double c = real(argv[1]), rate = real(argv[2]), mu = real(argv[3]);
            double duration = real(argv[4]), warmup = real(argv[5]);
            double seed_value = real(argv[6]);
            if (rate <= 0 || mu <= 0 || rate >= c * mu || duration <= 0 || duration > 600 ||
                warmup < 0 || warmup >= duration || seed_value < 0 || seed_value > 9007199254740991.0 ||
                std::floor(seed_value) != seed_value || rate * duration > max_requests * 0.9)
                throw std::invalid_argument("Invalid or excessive M/M/c workload");
            Kernel kernel(c, warmup);
            std::mt19937_64 rng(static_cast<std::uint64_t>(seed_value));
            std::exponential_distribution<double> interarrival(rate), service(mu);
            for (double at = interarrival(rng); at < duration; at += interarrival(rng))
                kernel.arrival(at, service(rng));
            kernel.print();
        } else {
            throw std::invalid_argument("Usage: mmc SERVERS LAMBDA MU DURATION WARMUP SEED; or mmc --trace SERVERS WARMUP");
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 2;
    }
}
