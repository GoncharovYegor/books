#!/bin/bash
# Runs the HTTP, start-up and GUI test suites on a sanitizer build and collects what the sanitizers report.
# Each program writes its reports to its own file (log_path), so a report from a server or a GUI the tests stop is kept.
#
# Usage: tools/run_sanitizers.sh <build dir>
#   The build folder is configured with -DFLIBRARY_SANITIZE=address,undefined or -DFLIBRARY_SANITIZE=thread (see tools/README.md).
# Exits with 1 if a suite fails or a sanitizer reports anything; the reports stay in the folder it prints.

set -u

# GCC 14's ThreadSanitizer cannot run with the address randomisation of newer kernels ("unexpected memory mapping"):
# run everything with it switched off, which the test scripts and the programs they start inherit
if [ -z "${FLIBRARY_SANITIZERS_NO_ASLR:-}" ]; then
	FLIBRARY_SANITIZERS_NO_ASLR=1 exec setarch "$(uname -m)" -R "$0" "$@"
fi

repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
build=$(cd "${1:?usage: run_sanitizers.sh <build dir>}" && pwd)
suppressions="$repo/tools/sanitizers"
reports=$(mktemp -d /tmp/flib-sanitizers.XXXXXX)

# Sanitized programs run several times slower; the GUI suite reads this to wait longer
export FLIBRARY_TEST_WAIT_MS=${FLIBRARY_TEST_WAIT_MS:-60000}
export ASAN_OPTIONS="log_path=$reports/asan:detect_leaks=1:strict_string_checks=1:check_initialization_order=1"
export LSAN_OPTIONS="suppressions=$suppressions/lsan.supp:print_suppressions=0"
export UBSAN_OPTIONS="log_path=$reports/ubsan:print_stacktrace=1:suppressions=$suppressions/ubsan.supp"
export TSAN_OPTIONS="log_path=$reports/tsan:second_deadlock_stack=1:suppressions=$suppressions/tsan.supp"

failures=()

run_suite()
{
	local name=$1
	shift
	echo "== $name"
	if ! "$@"; then
		failures+=("$name")
	fi
}

run_suite "HTTP tests" timeout 900 "$repo/src/home/tool/opds/test/http_test.sh" "$build"
run_suite "start-up tests" timeout 900 "$repo/src/home/flibrary/test/gui_startup_test.sh" "$build"
# ThreadSanitizer intercepts dlopen(), so the loader no longer searches the RUNPATH of the library that loads 7z.so:
# the library path is given explicitly, as the other two test scripts do
run_suite "GUI tests" bash -c 'cd "$1/bin" && LD_LIBRARY_PATH="$1/lib" QT_QPA_PLATFORM=offscreen QTEST_DISABLE_STACK_DUMP=1 timeout 3600 ./gui_tests' gui_tests "$build"

echo
shopt -s nullglob
report_files=("$reports"/*)
if [ ${#report_files[@]} -eq 0 ]; then
	echo "no sanitizer reports"
else
	echo "${#report_files[@]} sanitizer report files in $reports:"
	for file in "${report_files[@]}"; do
		# The first line of each report says what was found; the first frame in our code says where
		grep -hE '^(==[0-9]+==ERROR|WARNING: ThreadSanitizer|SUMMARY)|runtime error:' "$file" | sort | uniq -c | sed "s|^|  $(basename "$file"): |" | head -20
	done
fi

if [ ${#failures[@]} -gt 0 ]; then
	echo "failed: ${failures[*]}"
fi
if [ ${#failures[@]} -gt 0 ] || [ ${#report_files[@]} -gt 0 ]; then
	exit 1
fi
rmdir "$reports"
echo "all suites passed with no sanitizer reports"
