#!/usr/bin/python
# -*- coding: utf-8 -*-

__author__ = 'Alexey Litvinenko and Ilya Krylov'
__version__ = "1.0.0"
__maintainer__ = 'Alexey Litvinenko'
__email__ = "yeaxel@yandex.com"


import re
import argparse
import json
import os


def main():

    parser = argparse.ArgumentParser( \
            description="Вычисление числа таймаутов по phout / jtl логу. "
            "В случае JMeter предполагается лог "
            "jmeter*.jtl")
    parser.add_argument('-t', '--logtype', action='store',
            choices=['jmeter', 'phantom'],
            help="Тип лога (кастомный JMeter / стандартный "
            "phout*.log Phantom)", required=True)
    parser.add_argument('-v', '--ver', action='store',
            help="Версия тестируемого продукта",
            required=True)
    parser.add_argument('-f', '--fname', action='store',
            help="Имя файла с логом load tool",
            required=True)
    parser.add_argument('-c', '--cfg', action='store',
            help="Конфиг с таймаутами по типам запросов: "
            "в json формате либо ini-сценарий с "
            "секцией timeouts.",
            required=True)

    args = parser.parse_args()
    print "logtype: %s" % args.logtype
    print "ver: %s" % args.ver
    print "fname: %s" % os.path.abspath(args.fname)
    print "cfg: %s" % os.path.abspath(args.cfg)
    thresholds = {}
    try:
        with open(args.cfg, 'r') as cfg_file:
            thresholds = json.loads(cfg_file.read())
    except ValueError:
        import ConfigParser
        config = ConfigParser.ConfigParser()
        config.read(args.cfg)
        try:
            options = config.options('timeouts')
            for opt in options:
                try:
                    thresholds[opt] = float(config.get('timeouts',
                        opt))
                except ValueError, err:
                    msg = "ValueError in the 'timeouts.%s' option: "
                    msg += "%s."
                    print msg % (opt, err)
        except ConfigParser.Error, exc:
            print "Error in the %s file. %s." % (args.cfg, exc)

    print "Thresholds: %s" % thresholds

    peaks = PeaksCount(args.ver, args.logtype, args.fname, thresholds)
    report = peaks.get_report('raw')
    print '*' * 50
    print "Raw Report:\n%s" % report
    report = peaks.get_report('jira')
    print '*' * 50
    print "Jira Report:\n%s" % report


class PeaksCount(object):

    def __init__(self, version, log_type, log_file_path, thresholds):
        self.version = version
        self.log_type = log_type
        self.log_file_path = log_file_path
        self.thresholds = thresholds
        self.timeouts = {}
        self.reports = {}
        self.error_message = ''

    def _calc_timeouts(self):
        try:
            make_gen = lambda filename: (line.split('\t')
                                         for line in open(filename)
                                         if line.count('endTimeMillis', 0,
                                            len('endTimeMillis')) == 0 )

            if not self.log_file_path:
                self.error_message = "Log file with timeouts is not provided."
                return False

            try:
                file_try = make_gen(self.log_file_path)
                file_try.next()
            except:
                self.error_message = "Log file %s is empty." \
                                     % self.log_file_path
                return False

            file_list = make_gen(self.log_file_path)


            if self.log_type == 'jmeter':
                latency_idx, query_idx = 1, 2
                latency_multiplier = 10**(-3)
                status_code_idx = 6
            elif self.log_type == 'phantom':
                latency_idx, query_idx = 5, 1
                latency_multiplier = 10**(-6)
                status_code_idx = -1

            queries_dict = {}
            for line in file_list:
                latency = float(line[latency_idx]) * latency_multiplier
                query_tag = line[query_idx].lower()
                query_tag = re.sub('#\d+', '', query_tag)
                if not queries_dict.has_key(query_tag):
                    queries_dict[query_tag] = []
                queries_dict[query_tag].append(latency)

            values = {}
            values['timeouts'] = {}
            values['queries'] = {}
            for key in queries_dict.keys():
                values['queries'][key] = len([x
                                              for x in queries_dict[key]])
                if key in self.thresholds:
                    t_val = float(self.thresholds[key])
                    values['timeouts'][key] = \
                        (t_val, len([x for x in queries_dict[key]
                                     if x >= t_val]))
            if not values['timeouts']:
                self.error_message = "At least one sampleLabel should "
                self.error_message += "be specified in 'timeouts' "
                self.error_message += "section of ini-file."
                return False
            self.timeouts = values
            return True
        except Exception, exc:
            self.timeouts = {}
            self.reports['raw'] = ''
            self.reports['jira'] = ''
            self.error_message = "Exception on timeouts obtaining: %s" % exc
            return False

    def _generate_raw_report(self):
        qcount = sum(self.timeouts['queries'].values())
        tcount = sum([v[1] for v in self.timeouts['timeouts'].values()])
        tags = self.timeouts['timeouts'].keys()
        tags.sort()
        max_tag_len = max(len(t) for t in tags)
        report = ''
        dash_line = ''

        qtype_header = u"Тип запроса"
        timeouts_header = u"Количество таймаутов"
        percents_header = u"Процент от числа запросов данного типа"
        colwidth_1st = max(len(qtype_header), max_tag_len)
        colwidth_2nd = len(timeouts_header)
        colwidth_3rd = len(percents_header)
        report += u"Всего запросов: %d, " % qcount
        report += u"всего таймаутов: %d. " % tcount
        report += u"Процент таймаутов: %f%%\n" % \
                    (float(tcount) / float(qcount) * 100)
        row_text = "| %s | %s | %s |" % (qtype_header.center(colwidth_1st),
                                        timeouts_header.center(colwidth_2nd),
                                        percents_header.center(colwidth_3rd))
        dash_line = "-" * len(row_text)
        report += dash_line + "\n"
        report += row_text + "\n"
        report += dash_line + "\n"

        for tag in tags:
            qcount = self.timeouts['queries'][tag]
            tcount = self.timeouts['timeouts'][tag][1]

            col_1st = tag.center(colwidth_1st)
            col_2nd = str(tcount).center(colwidth_2nd)
            col_3rd = str(float(tcount) / float(qcount) * 100).center(colwidth_3rd)
            report += "| %s | %s | %s |\n" % (col_1st, col_2nd, col_3rd)
            report += dash_line + '\n'

        self.reports['raw'] = report


    def _generate_jira_report(self):
        qcount = sum(self.timeouts['queries'].values())
        tcount = sum([v[1] for v in self.timeouts['timeouts'].values()])
        share = float(tcount) / float(qcount) * 100
        tags = self.timeouts['timeouts'].keys()
        tags.sort()
        max_tag_len = max(len(t) for t in tags)
        report = ''
        dash_line = ''


        report += u"||Версия||Всего запросов||Всего таймаутов||"
        report += u"Процент от общего числа запросов||\n"
        report += "|%s|%d|%d|%f%%|\n" % \
                    (self.version, qcount, tcount, share)
        report += u"||Тип запроса||Таймаут||Количество запросов||"
        report += u"Количество таймаутов||"
        report += u"Процент от числа запросов данного типа||\n"

        for tag in tags:
            qcount = self.timeouts['queries'][tag]
            tcount = self.timeouts['timeouts'][tag][1]
            report += "|%s|%s|%d|" % (tag,
                                      self.timeouts['timeouts'][tag][0],
                                      qcount)
            report += "%d|%f%%|\n" % (tcount,
                                      float(tcount) / float(qcount) * 100)

        self.reports['jira'] = report

    def get_report(self, report_type):
        if not self.timeouts:
            if not self._calc_timeouts():
                return self.error_message
        if not self.reports.get(report_type):
            if report_type == 'raw':
                self._generate_raw_report()
            elif report_type == 'jira':
                self._generate_jira_report()
            else:
                self.error_message = "Report Type is not supported."
        if self.error_message:
            return self.error_message
        return self.reports.get(report_type)


if __name__ == '__main__':
    main()
