"""Public practice uses the day-three whole-map point rules.

    Authority: day-three slides 9, 10, 12. No technical/presentation points or
    legacy relative-performance scores are inferred from throughput results.
"""
import re

METHOD = 'public-final-practice-v1'
FAILURES = frozenset({'WRONG_ANSWER', 'OUTPUT_FORMAT', 'RUNTIME_ERROR', 'MEMORY_EXCEEDED',
                      'OUTPUT_LIMIT', 'LEFTOVER_PROCESSES'})


def judge_output(output, expected):
    lines = output.splitlines()
    if len(lines) != len(expected) or not all(re.fullmatch(r'-?[0-9]+', line) for line in lines):
        return 'OUTPUT_FORMAT'
    def canonical(line):
        digits = line.lstrip('-').lstrip('0') or '0'
        return ('-' if line.startswith('-') and digits != '0' else '') + digits
    return 'OK' if [canonical(line) for line in lines] == [str(v) for v in expected] else 'WRONG_ANSWER'


def summarize(records):
    correct = sum(r['status'] == 'OK' for r in records)
    incorrect = sum(r['status'] in FAILURES for r in records)
    return dict(correct=correct, incorrect=incorrect, score=correct - incorrect,
                processed=correct + incorrect,
                unfinished=sum(r['status'] == 'TIME_LIMIT' for r in records),
                memory_peak_mib=max((r.get('memory_peak_mib', 0) for r in records), default=0))
