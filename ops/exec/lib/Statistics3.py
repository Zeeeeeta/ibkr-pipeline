#!/usr/bin/env python3
"""Local substitute for /q/common/exec/lib/Statistics3."""

import math


class Statistics(object):

    def __init__(self, data):
        self.data = list(data) if data else []
        self.N = len(self.data)
        self.posN = sum(1 for x in self.data if x > 0)
        self.negN = sum(1 for x in self.data if x < 0)
        self.zeroN = sum(1 for x in self.data if x == 0)

        if self.N == 0:
            self.min = self.max = self.sum = self.mean = 0.0
            self.absmean = self.abssum = self.median = 0.0
            self.variance = self.stddev = self.tstat = self.sharpe = 0.0
            return

        self.min = self.data[0]
        self.max = self.data[-1]
        self.sum = sum(self.data)
        self.mean = self.sum / self.N

        abs_vals = [abs(x) for x in self.data]
        self.abssum = sum(abs_vals)
        self.absmean = self.abssum / self.N

        mid = self.N // 2
        if self.N % 2:
            self.median = self.data[mid]
        else:
            self.median = (self.data[mid - 1] + self.data[mid]) / 2.0

        self.variance = sum((x - self.mean) ** 2 for x in self.data) / self.N
        self.stddev = math.sqrt(self.variance) if self.variance > 0 else 0.0

        if self.stddev > 0 and self.N > 1:
            self.tstat = self.mean / (self.stddev / math.sqrt(self.N))
            self.sharpe = self.mean / self.stddev
        else:
            self.tstat = 0.0
            self.sharpe = 0.0
