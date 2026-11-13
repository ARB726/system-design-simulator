// Deterministic unit tests for the actual C++ kernel, independent of Python.
#define main mmc_cli_main
#include "mmc.cpp"
#undef main
#include <sstream>
#include <limits>

void check(bool condition) {
    if (!condition) throw std::runtime_error("Test assertion failed");
}

template<class F> void rejects(F action) {
    bool rejected = false;
    try { action(); } catch (const std::exception&) { rejected = true; }
    check(rejected);
}
void test_original_regressions() {
    Kernel parallel(2, 0);
    parallel.arrival(0, 4);
    parallel.arrival(0, 2);
    parallel.arrival(1, 1);
    check(parallel.measured == 3);
    check(std::abs(parallel.wait - 1) < 1e-12);
    check(std::abs(parallel.response - 8) < 1e-12);
    // Warmup excludes measurements, but its outstanding work still delays arrivals.
    Kernel warm(1, 2);
    warm.arrival(0, 5);
    warm.arrival(2, 1);
    check(warm.measured == 1 && warm.wait == 3 && warm.response == 4);
    rejects([] { Kernel k(1.5, 0); });
    rejects([] { Kernel k(1, -1); });
    rejects([] { real("2junk"); });
    rejects([] { real("nan"); });
    rejects([] { Kernel k(1, 0); k.arrival(2, 1); k.arrival(1, 1); });
    rejects([] { Kernel k(1, 0); k.arrival(0, 0); });
    rejects([] { Kernel k(1, 0); k.arrival(0, INFINITY); });
    rejects([] { Kernel k(1, 0); k.arrivals = max_requests; k.arrival(0, 1); });
    rejects([] { Kernel k(1, 0); k.arrival(1e308, 1e308); });
    rejects([] { Kernel k(1, 0); k.print(); });
    std::cout << "C++ kernel tests passed\n";
}

// Restore stream buffers/state even if a test fails.
struct Capture {
    std::istringstream input;
    std::ostringstream output, errors;
    std::streambuf *in, *out, *err;
    explicit Capture(const std::string& text) : input(text),
        in(std::cin.rdbuf(input.rdbuf())), out(std::cout.rdbuf(output.rdbuf())),
        err(std::cerr.rdbuf(errors.rdbuf())) { std::cin.clear(); }
    ~Capture() {
        std::cin.rdbuf(in); std::cout.rdbuf(out); std::cerr.rdbuf(err);
        std::cin.clear();
    }
};
struct Result { int code; std::string output, error; };
Result cli(std::vector<std::string> args, const std::string& input = "") {
    args.insert(args.begin(), "mmc");
    std::vector<char*> argv;
    for (auto& arg : args) argv.push_back(arg.data());
    Capture capture(input);
    int code = mmc_cli_main(static_cast<int>(argv.size()), argv.data());
    return {code, capture.output.str(), capture.errors.str()};
}
void bad_cli(const std::vector<std::string>& args, const std::string& input = "") {
    auto result = cli(args, input);
    check(result.code == 2 && result.output.empty() && !result.error.empty());
}
void test_idle_server_has_no_wait() {
    Kernel k(1, 0); k.arrival(10, 2);
    check(k.wait == 0 && k.response == 2);
}
void test_queue_drains_before_later_arrival() {
    Kernel k(1, 0); k.arrival(0, 2); k.arrival(1, 2); k.arrival(10, 1);
    check(k.wait == 1 && k.response == 6);
}
void test_simultaneous_requests_use_both_servers() {
    Kernel k(2, 0); k.arrival(0, 3); k.arrival(0, 3);
    check(k.wait == 0 && k.response == 6);
}
void test_exact_warmup_boundary_is_measured() {
    Kernel k(1, 5); k.arrival(4, 1); k.arrival(5, 2);
    check(k.arrivals == 2 && k.measured == 1 && k.response == 2);
}
void test_measurement_excludes_earlier_arrivals() {
    Kernel k(1, 5); k.arrival(0, 10);
    check(k.measured == 0); rejects([&] { k.print(); });
}
void test_exact_request_limit_is_allowed() {
    Kernel k(1, 0); k.arrivals = max_requests - 1; k.arrival(0, 1);
    check(k.arrivals == max_requests && k.measured == 1);
}
void test_aggregate_response_overflow_rejected() {
    Kernel k(2, 0); k.arrival(0, 1e308);
    rejects([&] { k.arrival(0, 1e308); });
}
void test_negative_arrival_rejected() {
    rejects([] { Kernel k(1, 0); k.arrival(-1, 1); });
}
void test_nan_arrival_rejected() {
    rejects([] { Kernel k(1, 0); k.arrival(std::numeric_limits<double>::quiet_NaN(), 1); });
}
void test_maximum_server_count_allowed() { Kernel k(4096, 0); check(k.available.size() == 4096); }
void test_too_many_servers_rejected() { rejects([] { Kernel k(4097, 0); }); }
void test_fractional_numeric_argument_parsed() { check(real("1.25") == 1.25); }
void test_exponent_numeric_argument_parsed() { check(real("1e2") == 100); }
void test_empty_numeric_argument_rejected() { rejects([] { real(""); }); }
void test_infinite_numeric_argument_rejected() { rejects([] { real("inf"); }); }
void test_cli_missing_arguments() { bad_cli({}); }
void test_cli_unknown_mode() { bad_cli({"--other", "1", "0"}); }
void test_cli_empty_trace() { bad_cli({"--trace", "1", "0"}); }
void test_cli_incomplete_trace() { bad_cli({"--trace", "1", "0"}, "0"); }
void test_cli_malformed_trace() { bad_cli({"--trace", "1", "0"}, "broken"); }
void test_cli_unsorted_trace() { bad_cli({"--trace", "1", "0"}, "2 1\n1 1\n"); }
void test_cli_zero_service_trace() { bad_cli({"--trace", "1", "0"}, "0 0\n"); }
void test_cli_valid_trace_json() {
    auto r = cli({"--trace", "1", "0"}, "0 2\n1 2\n5 1\n");
    check(r.code == 0 && r.error.empty());
    check(r.output.find("\"requests\":3") != std::string::npos);
    check(r.output.find("\"mean_response_s\":2") != std::string::npos);
}
void test_cli_saturated_workload() { bad_cli({"2", "100", "50", "30", "1", "7"}); }
void test_cli_negative_rate() { bad_cli({"2", "-1", "50", "30", "1", "7"}); }
void test_cli_zero_service_rate() { bad_cli({"2", "10", "0", "30", "1", "7"}); }
void test_cli_excessive_duration() { bad_cli({"2", "10", "50", "601", "1", "7"}); }
void test_cli_warmup_equals_duration() { bad_cli({"2", "10", "50", "30", "30", "7"}); }
void test_cli_fractional_seed() { bad_cli({"2", "10", "50", "30", "1", "1.5"}); }
void test_cli_negative_seed() { bad_cli({"2", "10", "50", "30", "1", "-1"}); }
void test_cli_excessive_seed() { bad_cli({"2", "10", "50", "30", "1", "9007199254740992"}); }
void test_cli_arrival_budget() { bad_cli({"4096", "4000", "50", "600", "1", "7"}); }
void test_cli_seed_reproducibility() {
    std::vector<std::string> args = {"4", "100", "50", "30", "1", "7"};
    auto a = cli(args), b = cli(args);
    check(a.code == 0 && b.code == 0 && a.output == b.output && a.error.empty());
}

int main() {
    int failures = 0;
    try { test_original_regressions(); std::cout << "PASS test_original_regressions\n"; } catch (const std::exception& e) { ++failures; std::cerr << "FAIL test_original_regressions: " << e.what() << "\n"; }
    try { test_idle_server_has_no_wait(); std::cout << "PASS test_idle_server_has_no_wait\n"; } catch (const std::exception& e) { ++failures; std::cerr << "FAIL test_idle_server_has_no_wait: " << e.what() << "\n"; }
    try { test_queue_drains_before_later_arrival(); std::cout << "PASS test_queue_drains_before_later_arrival\n"; } catch (const std::exception& e) { ++failures; std::cerr << "FAIL test_queue_drains_before_later_arrival: " << e.what() << "\n"; }
    try { test_simultaneous_requests_use_both_servers(); std::cout << "PASS test_simultaneous_requests_use_both_servers\n"; } catch (const std::exception& e) { ++failures; std::cerr << "FAIL test_simultaneous_requests_use_both_servers: " << e.what() << "\n"; }
    try { test_exact_warmup_boundary_is_measured(); std::cout << "PASS test_exact_warmup_boundary_is_measured\n"; } catch (const std::exception& e) { ++failures; std::cerr << "FAIL test_exact_warmup_boundary_is_measured: " << e.what() << "\n"; }
    try { test_measurement_excludes_earlier_arrivals(); std::cout << "PASS test_measurement_excludes_earlier_arrivals\n"; } catch (const std::exception& e) { ++failures; std::cerr << "FAIL test_measurement_excludes_earlier_arrivals: " << e.what() << "\n"; }
    try { test_exact_request_limit_is_allowed(); std::cout << "PASS test_exact_request_limit_is_allowed\n"; } catch (const std::exception& e) { ++failures; std::cerr << "FAIL test_exact_request_limit_is_allowed: " << e.what() << "\n"; }
    try { test_aggregate_response_overflow_rejected(); std::cout << "PASS test_aggregate_response_overflow_rejected\n"; } catch (const std::exception& e) { ++failures; std::cerr << "FAIL test_aggregate_response_overflow_rejected: " << e.what() << "\n"; }
    try { test_negative_arrival_rejected(); std::cout << "PASS test_negative_arrival_rejected\n"; } catch (const std::exception& e) { ++failures; std::cerr << "FAIL test_negative_arrival_rejected: " << e.what() << "\n"; }
    try { test_nan_arrival_rejected(); std::cout << "PASS test_nan_arrival_rejected\n"; } catch (const std::exception& e) { ++failures; std::cerr << "FAIL test_nan_arrival_rejected: " << e.what() << "\n"; }
    try { test_maximum_server_count_allowed(); std::cout << "PASS test_maximum_server_count_allowed\n"; } catch (const std::exception& e) { ++failures; std::cerr << "FAIL test_maximum_server_count_allowed: " << e.what() << "\n"; }
    try { test_too_many_servers_rejected(); std::cout << "PASS test_too_many_servers_rejected\n"; } catch (const std::exception& e) { ++failures; std::cerr << "FAIL test_too_many_servers_rejected: " << e.what() << "\n"; }
    try { test_fractional_numeric_argument_parsed(); std::cout << "PASS test_fractional_numeric_argument_parsed\n"; } catch (const std::exception& e) { ++failures; std::cerr << "FAIL test_fractional_numeric_argument_parsed: " << e.what() << "\n"; }
    try { test_exponent_numeric_argument_parsed(); std::cout << "PASS test_exponent_numeric_argument_parsed\n"; } catch (const std::exception& e) { ++failures; std::cerr << "FAIL test_exponent_numeric_argument_parsed: " << e.what() << "\n"; }
    try { test_empty_numeric_argument_rejected(); std::cout << "PASS test_empty_numeric_argument_rejected\n"; } catch (const std::exception& e) { ++failures; std::cerr << "FAIL test_empty_numeric_argument_rejected: " << e.what() << "\n"; }
    try { test_infinite_numeric_argument_rejected(); std::cout << "PASS test_infinite_numeric_argument_rejected\n"; } catch (const std::exception& e) { ++failures; std::cerr << "FAIL test_infinite_numeric_argument_rejected: " << e.what() << "\n"; }
    try { test_cli_missing_arguments(); std::cout << "PASS test_cli_missing_arguments\n"; } catch (const std::exception& e) { ++failures; std::cerr << "FAIL test_cli_missing_arguments: " << e.what() << "\n"; }
    try { test_cli_unknown_mode(); std::cout << "PASS test_cli_unknown_mode\n"; } catch (const std::exception& e) { ++failures; std::cerr << "FAIL test_cli_unknown_mode: " << e.what() << "\n"; }
    try { test_cli_empty_trace(); std::cout << "PASS test_cli_empty_trace\n"; } catch (const std::exception& e) { ++failures; std::cerr << "FAIL test_cli_empty_trace: " << e.what() << "\n"; }
    try { test_cli_incomplete_trace(); std::cout << "PASS test_cli_incomplete_trace\n"; } catch (const std::exception& e) { ++failures; std::cerr << "FAIL test_cli_incomplete_trace: " << e.what() << "\n"; }
    try { test_cli_malformed_trace(); std::cout << "PASS test_cli_malformed_trace\n"; } catch (const std::exception& e) { ++failures; std::cerr << "FAIL test_cli_malformed_trace: " << e.what() << "\n"; }
    try { test_cli_unsorted_trace(); std::cout << "PASS test_cli_unsorted_trace\n"; } catch (const std::exception& e) { ++failures; std::cerr << "FAIL test_cli_unsorted_trace: " << e.what() << "\n"; }
    try { test_cli_zero_service_trace(); std::cout << "PASS test_cli_zero_service_trace\n"; } catch (const std::exception& e) { ++failures; std::cerr << "FAIL test_cli_zero_service_trace: " << e.what() << "\n"; }
    try { test_cli_valid_trace_json(); std::cout << "PASS test_cli_valid_trace_json\n"; } catch (const std::exception& e) { ++failures; std::cerr << "FAIL test_cli_valid_trace_json: " << e.what() << "\n"; }
    try { test_cli_saturated_workload(); std::cout << "PASS test_cli_saturated_workload\n"; } catch (const std::exception& e) { ++failures; std::cerr << "FAIL test_cli_saturated_workload: " << e.what() << "\n"; }
    try { test_cli_negative_rate(); std::cout << "PASS test_cli_negative_rate\n"; } catch (const std::exception& e) { ++failures; std::cerr << "FAIL test_cli_negative_rate: " << e.what() << "\n"; }
    try { test_cli_zero_service_rate(); std::cout << "PASS test_cli_zero_service_rate\n"; } catch (const std::exception& e) { ++failures; std::cerr << "FAIL test_cli_zero_service_rate: " << e.what() << "\n"; }
    try { test_cli_excessive_duration(); std::cout << "PASS test_cli_excessive_duration\n"; } catch (const std::exception& e) { ++failures; std::cerr << "FAIL test_cli_excessive_duration: " << e.what() << "\n"; }
    try { test_cli_warmup_equals_duration(); std::cout << "PASS test_cli_warmup_equals_duration\n"; } catch (const std::exception& e) { ++failures; std::cerr << "FAIL test_cli_warmup_equals_duration: " << e.what() << "\n"; }
    try { test_cli_fractional_seed(); std::cout << "PASS test_cli_fractional_seed\n"; } catch (const std::exception& e) { ++failures; std::cerr << "FAIL test_cli_fractional_seed: " << e.what() << "\n"; }
    try { test_cli_negative_seed(); std::cout << "PASS test_cli_negative_seed\n"; } catch (const std::exception& e) { ++failures; std::cerr << "FAIL test_cli_negative_seed: " << e.what() << "\n"; }
    try { test_cli_excessive_seed(); std::cout << "PASS test_cli_excessive_seed\n"; } catch (const std::exception& e) { ++failures; std::cerr << "FAIL test_cli_excessive_seed: " << e.what() << "\n"; }
    try { test_cli_arrival_budget(); std::cout << "PASS test_cli_arrival_budget\n"; } catch (const std::exception& e) { ++failures; std::cerr << "FAIL test_cli_arrival_budget: " << e.what() << "\n"; }
    try { test_cli_seed_reproducibility(); std::cout << "PASS test_cli_seed_reproducibility\n"; } catch (const std::exception& e) { ++failures; std::cerr << "FAIL test_cli_seed_reproducibility: " << e.what() << "\n"; }
    std::cout << "34 tests, " << failures << " failures\n";
    return failures ? 1 : 0;
}
