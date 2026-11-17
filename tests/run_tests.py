#!/usr/bin/env python3
"""Chạy toàn bộ test unit + tích hợp của Mango Server 1.0.

  cd ~/workspace/mango-server
  .venv/bin/python tests/run_tests.py        # chạy hết
  .venv/bin/python tests/run_tests.py -k auth  # chỉ test có tên chứa 'auth'

Test nào cần máy thật (Windows/may-01/máy ảo) sẽ được ghi rõ trong báo cáo
là CHƯA KIỂM CHỨNG, không gộp vào số pass/fail ở đây.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "server"))


def main():
    pattern = "*"
    if "-k" in sys.argv:
        idx = sys.argv.index("-k")
        if idx + 1 < len(sys.argv):
            pattern = f"*{sys.argv[idx + 1]}*"
    loader = unittest.TestLoader()
    suite = loader.discover(HERE, pattern="test_*.py")
    if pattern != "*":
        keyword = pattern.strip("*")
        filtered = unittest.TestSuite()
        for s in suite:
            for test in s:
                if keyword in str(test):
                    filtered.addTest(test)
        suite = filtered
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
