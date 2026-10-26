#!/usr/bin/env python3


import sys
import os
import datetime
import re
import time
import copy
import gzip
import fnmatch
import inspect
import glob
import pdb 

from collections import defaultdict
from optparse import OptionParser
from operator import itemgetter, attrgetter
from decimal import *

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_LOCAL_LIB = os.path.normpath(os.path.join(_SCRIPT_DIR, '..', 'lib'))
_LEGACY_LIB = '/q/common/exec/lib'
for _lib in (_LOCAL_LIB, _LEGACY_LIB):
    if os.path.isdir(_lib) and _lib not in sys.path:
        sys.path.insert(0, _lib)

import FileUtil
from Utilities import niceNum
from BusinessDays import BusinessDays
from Statistics3 import Statistics


def _cell_to_yyyymmdd(val):
    """Normalize a table cell to YYYYMMDD for date-range filtering (parquet paths)."""
    if val is None or val == '':
        return None
    if isinstance(val, bool):
        return None
    if isinstance(val, int):
        s = str(val)
        if len(s) == 8 and s.isdigit():
            return s
        return None
    if isinstance(val, float):
        if val != val:  # NaN
            return None
        i = int(val)
        if float(i) == val:
            return _cell_to_yyyymmdd(i)
        return None
    if hasattr(val, 'strftime'):
        try:
            return val.strftime('%Y%m%d')
        except Exception:
            pass
    s = str(val).strip()
    if len(s) >= 8 and s[:8].isdigit():
        return s[:8]
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%m/%d/%Y'):
        try:
            return datetime.datetime.strptime(s[:10], fmt).strftime('%Y%m%d')
        except ValueError:
            continue
    return None


def _parquet_to_csv_lines_via_duckdb(path, start, end):
    """
    Read Parquet without pyarrow/fastparquet using DuckDB (pip install duckdb).
    Returns the same shape as pandas: list of CSV text lines including header.
    """
    import csv as csv_mod
    import io

    import duckdb

    conn = duckdb.connect(database=':memory:')
    result = conn.execute('SELECT * FROM read_parquet(?)', [path])
    colnames = [d[0] for d in result.description]
    rows = result.fetchall()

    if start is not None and end is not None and 'date' in colnames:
        di = colnames.index('date')
        filt = []
        for row in rows:
            ymd = _cell_to_yyyymmdd(row[di])
            if ymd is not None and start <= ymd <= end:
                filt.append(row)
        rows = filt

    buf = io.StringIO()
    writer = csv_mod.writer(buf, lineterminator='\n')
    writer.writerow(colnames)
    for row in rows:
        writer.writerow(row)
    text = buf.getvalue()
    return text.split('\n')


def startUp():

    usage = "usage: %prog [ options ] FILE_NAME"
    parser = OptionParser(usage)
    parser.add_option( "-s", "--startdate"    ,     dest="startdate"   , help="StartDate"                                                                 )
    parser.add_option( "-e", "--enddate"      ,     dest="enddate"     , help="EndDate"                                                                   )
    parser.add_option( "-d", "--delim"        ,     dest="delim"       , help="Delimiter Of The File [ default : %default ]"          ,  default=','      )
    parser.add_option(       "--dispdelim"    ,     dest="dispdelim"   , help="Delimiter For Display OutPut [ default : %default ] "   ,  default='|'     )
    parser.add_option(       "--skiplines"    ,     dest="skiplines"   , help="SkipLines [ default : %default ] "                      ,  default=0       )
    parser.add_option( "-c", "--cols"         ,     dest="cols"        , help="Columns To Display"                                                        )
    parser.add_option(       "--top"          ,     dest="top"         , help="Show These Top Result Rows [ default : %default ]"     ,  default=0        )
    parser.add_option(       "--last"         ,     dest="last"        , help="Show These Last Result Rows [ default : %default ]"    ,  default=0        )
    parser.add_option(       "--sortcol"      ,     dest="sortcol"     , help="Sort On These Columns"                                                     )
    parser.add_option(       "--rsortcol"     ,     dest="rsortcol"    , help="Reverse Sort On These Columns"                                             )
    parser.add_option(       "--sorttype"     ,     dest="sorttype"    , help="Sort Type [ default : %default ] "   ,  default="numeric"                  )
    parser.add_option( "-m", "--match"        ,     dest="match"       , help="Match The Following Lines"                         ,  action="append"      )
    parser.add_option(       "--exclmatch"    ,     dest="exclmatch"   , help="Exclude Match [ Opp of -m Option ]"                ,  action="append"      )
    parser.add_option(       "--showfilename" ,     dest="showfilename", help="Show FileName [ Colname : file_name ] ",  default=False   ,  action="store_true"  )
    parser.add_option(       "--showfiledate" ,     dest="showfiledate", help="Show FileDate [ Colname : file_date ] ",  default=False   ,  action="store_true"  )
    parser.add_option( "-r", "--match_pattern",     dest="match_pattern",help="Match Pattern [ 'symbol == \"xxxxx\"' ]"    ,                            )
    parser.add_option( "-v", "--vertical"     ,     dest="vertical"    , help="Display Veritcal Data"          ,  default=False   ,  action="store_true"  )
    parser.add_option( "-t", "--transpose"    ,     dest="transpose"   , help="Display Transpose Data"         ,  default=False   ,  action="store_true"  )
    parser.add_option( "-b", "--bottom"       ,     dest="bottom"      , help="Print  Header At Bottom"        ,  default=False   ,  action="store_true"  )
    parser.add_option(       "--showstats"    ,     dest="showstats"   , help="Show Statistics"                ,  default=False   ,  action="store_true"  )
    parser.add_option( "-f", "--tailf"        ,     dest="tailf"       , help="Tail -f"                        ,  default=None    ,  action="store_true"  )
    parser.add_option(       "--expr"         ,     dest="expr"        , help="Execute This Expression y=cola+colb"               ,  action="append"      )
    parser.add_option(       "--topdata"      ,     dest="topdata"     , help="Process Only These Top Data Rows",  default=0                              )
    parser.add_option(       "--smartdisplay" ,     dest="smartdisplay", help="Show Formatted OutPut"          ,  default=False   ,  action="store_true"  )
    parser.add_option(       "--showonlystats",     dest="showonlystats",help="Show Only Stats Without Any Data", default=False   ,  action="store_true"  )
    parser.add_option(       "--dispmidheader",     dest="dispmidheader",help="Show Header After Every 15 lines", default=False   ,  action="store_true"  )
    parser.add_option(       "--raw"          ,     dest="raw"         , help="Show Raw"                       ,  default=False   ,  action="store_true"  )
    parser.add_option(       "--excols"       ,     dest="excols"      , help="Columns To Exclude From Display"                                           )
    parser.add_option(       "--rawcsv"       ,     dest="rawcsv"      , help="Show Raw CSV Format"            ,  default=False   ,  action="store_true"  )
    parser.add_option(       "--vh"           ,     dest="vh"          , help="Show Only Header Row"           ,  default=False   ,  action="store_true"  )
    parser.add_option(       "--colsmatch"    ,     dest="colsmatch"   , help="Display Columns Matching Pattern"                  ,  action="append"      )
    parser.add_option(       "--showstatsonly",     dest="showstatsonly",help="Show Only Stats Without Any Data", default=False   ,  action="store_true"  )
    parser.add_option(       "--removeheaderspaces",dest="removeheaderspaces", help="Remove Spaces From Header With UnderScore" , default=False   ,  action="store_true"  )
    parser.add_option(       "--disablesmartcommas",dest="disablesmartcommas", help="Do not try to preserve commmas in quotes",default=False, action="store_true" )
    parser.add_option(       "--cleanupheadercols" ,dest="cleanupheadercols" , help="Clean Up Non AlphaNumeric From Header Names With UnderScore" , default=False, action="store_true" )
    parser.add_option(       "--filetype"     ,     dest="filetype"    , help="File Type ( incase file extensions not present )" , default=None           )


    global options
    ( options, args ) = parser.parse_args()
    if options.showfilename == True and options.showfiledate == True : parser.error ( usage )
    #if len(args) == 0  : parser.error ( usage )
    if options.rawcsv == True :
        options.raw = True
        options.dispdelim = ","

    if options.showstatsonly == True : options.showonlystats = True
    if options.vh == True : options.vertical = True

    return args


class FileDataReader ( object ) :

    def __init__ ( self , file_name , options ) :

        self.data_list   = list()
        self.header_list = list()
        self.file_name   = file_name
        self.options     = options
        self.maxcolfields = 0
        self.fixdatalistlength = False
        self.match_list = list()
        self.exclmatch_list = list()
        self.fdl = None
        self.first_header_field_name = ''
        self.fdl_tell = 0
        self.file_date = ''

        if self.file_name is not None and type(self.file_name) != type(sys.stdin) :
            #match_date = re.search ( '(\d{8})', self.file_name  )
            #if match_date is not None :
            #    self.file_date = match_date.group(1)
            match_date = re.findall ( r'(\d{8})', self.file_name )
            if match_date and len(match_date) > 0 :
                self.file_date = match_date[-1]

        if self.options.match is not None :
            for match_pattern in self.options.match :
                self.match_list.append ( re.compile ( match_pattern ) )

        if self.options.exclmatch is not None :
            for match_excl_pattern in self.options.exclmatch :
                self.exclmatch_list.append ( re.compile ( match_excl_pattern ) )

        #print "Processing File : %s" % file_name


    def matchConditionCheck ( self, line ) :

        total_match_count = 0
        total_match_conditions = len(self.match_list)
        match_status = False
        for match_pattern in self.match_list :
            if re.search ( match_pattern, line ) : total_match_count += 1
        if total_match_count == total_match_conditions : match_status =  True
        #if total_match_count > 0  : match_status =  True

        return match_status

    def matchExclConditionCheck ( self, line ) :

        total_match_count = 0
        total_match_condition = len(self.exclmatch_list)
        match_status = False
        for match_excl_pattern in self.exclmatch_list :
            if re.search ( match_excl_pattern, line ) :
                return False
        return True


    def populateExtraColumns ( self, data_list, header_list ) :

        if len(header_list) < self.maxcolfields :
            total_header_list_length = len(header_list)
            header_list = header_list + [ "ex_col_" + str( i + 1  - total_header_list_length ) for i in range(  total_header_list_length, self.maxcolfields ) ]

        total_header_list_length = len(header_list)
        if self.fixdatalistlength == True :
            for row_num, row in enumerate ( data_list ) :
                row_data_length = len(row)
                if row_data_length < total_header_list_length :
                    row = row + [ '' for i in range ( row_data_length, total_header_list_length ) ]
                    data_list[row_num] = row

        return ( data_list, header_list )

    def loadParqFeatherFile ( self ):

        start = self.options.startdate
        end = self.options.enddate
        parqDf = None
        name = self.file_name
        ftype = self.options.filetype or ''

        if re.search(r'parq|parquet', name, re.I) or re.search(r'parq|parquet', ftype, re.I):
            try:
                import pandas as pd
            except ImportError:
                return _parquet_to_csv_lines_via_duckdb(self.file_name, start, end)

            pd.set_option('mode.chained_assignment', None)

            engines_tried = []
            for engine in ('pyarrow', 'fastparquet'):
                try:
                    parqDf = pd.read_parquet(self.file_name, engine=engine)
                    break
                except Exception as err:
                    engines_tried.append((engine, err))
                    continue
            if parqDf is None:
                try:
                    return _parquet_to_csv_lines_via_duckdb(self.file_name, start, end)
                except ImportError as err:
                    hint = (
                        'Install pyarrow (pip install pyarrow), fastparquet, or duckdb '
                        '(pip install duckdb) to read Parquet.'
                    )
                    detail = '; '.join('%s: %s' % (e, type(exc).__name__) for e, exc in engines_tried)
                    raise ImportError('%s Underlying errors: %s' % (hint, detail)) from err
        elif re.search(r'feather', name, re.I) or re.search(r'feather', ftype, re.I):
            import pandas as pd

            pd.set_option('mode.chained_assignment', None)

            try:
                parqDf = pd.read_feather(self.file_name)
            except ImportError as err:
                raise ImportError(
                    'Reading Feather requires pyarrow (pip install pyarrow).'
                ) from err
            if parqDf is not None and 'index' in parqDf.columns:
                parqDf = parqDf.set_index('index')

        if parqDf is None:
            raise ValueError('Could not load parquet/feather file: %s' % self.file_name)

        if start is not None and end is not None and 'date' in parqDf.columns.tolist():
            if str(parqDf['date'].dtype) == 'int64':
                parqDf['date'] = pd.to_datetime(parqDf['date'])
            if hasattr(parqDf['date'], 'dt'):
                parqDf['date'] = parqDf['date'].dt.strftime('%Y%m%d')
            else:
                parqDf['date'] = parqDf['date'].astype(str)
            parqDf = parqDf.loc[(parqDf['date'] >= start) & (parqDf['date'] <= end)]
        parqFdl = parqDf.to_csv(index=False).split('\n')

        return parqFdl


    def processData ( self, data_list, header_list ) :

        file_name = ""
        file_header_list = list()

        if self.fdl is None :
            if type(self.file_name) == type ( sys.stdin ) :
                fdl = self.file_name
                file_name = 'STDIN'
            elif fnmatch.fnmatch(self.file_name, '*.gz') :
                fdl = gzip.open(self.file_name, 'rt')
                file_name = self.file_name
            elif ( fnmatch.fnmatch(self.file_name, '*.parq')
                   or fnmatch.fnmatch(self.file_name, '*.parquet')
                   or fnmatch.fnmatch(self.file_name, '*feather')
                   or ( options.filetype and re.search ( 'feather|parq', options.filetype ) ) ):
                fdl = self.loadParqFeatherFile()
                file_name = self.file_name
            else :
                fdl = open(self.file_name, 'r')
                file_name = self.file_name
        else :
            fdl       = self.fdl
            file_name = self.file_name
            file_header_list = header_list[:]
            fdl.seek ( self.fdl_tell, 0 )

        counter = 0
        total_header_elements = 0
        max_counter = 20000

        for line in fdl :

            #re.sub(',(?=[^"]*"[^"]*(?:"[^"]*"[^"]*)*$)',"",string)
            #if counter >= max_counter and counter % max_counter  == 0 : sys.stderr.write ( "." )
            line = line.rstrip ( '\n' )
            if line is None or line == '' : continue
            counter += 1

            if counter <= int(self.options.skiplines) : continue ## skip these many lines
            if int(options.topdata) > 0 and counter > int(options.topdata) : break
            if len(file_header_list) != 0 and self.options.match and self.matchConditionCheck ( line ) != True : continue
            if len(file_header_list) != 0 and self.options.exclmatch and self.matchExclConditionCheck ( line ) != True : continue

            # line = re.sub(',(?=[^"]*"[^"]*(?:"[^"]*"[^"]*)*$)',"\01",line) ## Replace comma between double quotes with \01 for later change
            # line = re.sub(",(?=[^']*'[^']*(?:'[^']*'[^']*)*$)","\01",line) ## Replace comma between double quotes with \01 for later change
            if not options.disablesmartcommas:
                while re.search('"([^",]+),([^"]+)"', line): #while we have commas within quotes, replace them one by one with \x01
                    line = re.sub('"([^",]+),([^"]+)"',r'"\1\01\2"', line)
                #line = re.sub('"([^",]+),([^"]+)"',r'"\1\01\2"', line)
                #line = re.sub("'([^',]+),([^']+)'",r"'\1\01\2'", line)

            line_data_list = line.split ( self.options.delim )
            line_data_list = [ rec.strip() for rec in line_data_list ]
            if not options.disablesmartcommas:
                line_data_list = [ re.sub ( "\01", "," , rec ) for rec in line_data_list ]
            line_data_list = [ re.sub ( '"', '', rec )  for rec in line_data_list ]
            line_data_list = [ re.sub ( "'", '', rec )  for rec in line_data_list ]

            if len(file_header_list) == 0 or ( self.first_header_field_name != '' and self.first_header_field_name == line_data_list[0] ) : ## process the header line
                self.first_header_field_name  = line_data_list[0]
                if self.options.showfiledate == True :
                    line_header_list = [ 'file_date' ] + line_data_list
                else :
                    line_header_list = [ 'file_name' ] + line_data_list
                if self.maxcolfields < len(line_header_list):
                    self.maxcolfields = len(line_header_list)
                file_header_list = line_header_list[:]
                #if len(header_list) == 0 :
                header_list = file_header_list[:]
                total_header_elements = len( header_list )
            else :
                if self.options.showfiledate == True :
                    line_data_list = [ self.file_date ] + line_data_list
                else :
                    line_data_list = [ file_name ] + line_data_list
                data_list.append ( line_data_list )
                if self.maxcolfields < len(line_data_list) :
                    self.maxcolfields = len(line_data_list)
                    self.fixdatalistlength = True
                if self.maxcolfields != len(line_data_list):
                    self.fixdatalistlength = True

        data_list, header_list = self.populateExtraColumns ( data_list, header_list )


        if ( file_name != 'STDIN' and options.topdata == 0
             and not re.search ( r'parq|feather|parquet', file_name, re.I )
             and not ( options.filetype and re.search ( r'parq|feather', options.filetype, re.I ) ) ):
            self.fdl_tell = fdl.tell()

        self.fdl = fdl
        #print header_list
        return ( data_list, header_list )



class Table ( object ) :

    def __init__ ( self, data_list, header_list , options ) :

        self.data_list   = data_list
        self.header_list = header_list
        self.options     = options
        self.cols_dict   = self.checkHeader ( header_list )
        self.match_pattern_cols_dict = dict()
        self.first_run   = False

        self.cols_field_max_length_dict = dict()
        for col in list(self.cols_dict.keys()):
            self.cols_field_max_length_dict[col] = len(col)


    def setDataList ( self, data_list ) :

        self.data_list = data_list

    def checkHeader ( self, header_list ) :

        cols_dict = dict()
        for index, col in enumerate ( header_list ) :
            cols_dict[col] = index
        return cols_dict


    def createSearchExecString ( self  ) :

        search_exec_list = list()
        if self.options.match_pattern is not None :
            search_exec_list.append ( self.options.match_pattern )
        if self.options.expr is not None :
            for expr in self.options.expr :
                search_exec_list.append ( expr )

        if len(search_exec_list) == 0 :
            self.search_exec_string = None
        else :
            self.search_exec_string =  ( ','.join ( search_exec_list ) )


    def getStatusOfMatchPatternPerRequest ( self, row ) :

        if self.options.match_pattern is None :
            match_status = True
        else :
            match_status = False

        for index, col in enumerate ( self.header_list ) :

            if self.first_run == True and col not in self.match_pattern_cols_dict : continue
            try :
                data_value  = row[index]

                if self.first_run ==  False :
                    if not re.search ( col, self.search_exec_string ) :
                        continue
                    else :
                        self.match_pattern_cols_dict[col] = col

                if re.search ( '[A-Z:]' , data_value, re.I ) or data_value == '' : ## these are not numbers
                    assign_string = '%s="%s"' % ( col , data_value )
                else :
                    assign_string = '%s=%s' % ( col , Decimal(data_value) )

                exec( assign_string )

            except :
                pass

        self.first_run = True


        if self.options.match_pattern is not None and eval ( self.options.match_pattern ) == False :
            return ( False, row )


        if self.options.expr is not None :
            for eval_expr in self.options.expr :
                if re.search ( '=' , eval_expr ) :
                    ( col_name, eval_expr ) = eval_expr.split("=",1)
                try :
                    eval_expr_value = eval ( eval_expr )
                except :
                    eval_expr_value = ''
                row.append ( str(eval_expr_value) )

        return ( True , row )

    def setColumnsToDisplayByMatch ( self ) :

        #for match_excl_pattern in self.options.exclmatch :
        display_cols_list = list()
        if self.options.cols :
            display_cols_list = self.options.cols.split(",")
        header_list = self.header_list

        for colmatch in options.colsmatch  :
            for header_name in header_list  :
                if re.search ( colmatch, header_name ) and header_name not in display_cols_list :
                    display_cols_list.append  ( header_name )
        self.options.cols = ",".join ( display_cols_list )


    def processDataPerRequest ( self ) :


        if self.options.vh == True :
            self.data_list = list()
            if self.options.transpose == True or self.options.vertical == True :
                empty_data_list = [ '' for x in self.header_list ]
                self.data_list.append ( empty_data_list )


        filtered_data_list = list()

        ## add the extra columns in the header for the expressions options.
        if self.options.expr is not None :
            for eval_expr in self.options.expr :
                if re.search ( '=', eval_expr ) :
                    ( col_name, eval_expr ) = eval_expr.split("=", 1 )
                else :
                    col_name = eval_expr
                self.addExtraHeaderCol ( col_name )

        self.createSearchExecString (  )

        max_counter = 20000

        for counter, row in enumerate ( self.data_list ) :
            #if counter >= max_counter and counter % max_counter  == 0 : sys.stderr.write ( "." )
            ## do the match_pattern here to see if this row in needed
            if self.options.match_pattern is not None or self.options.expr is not None :
                ( row_status, row ) = self.getStatusOfMatchPatternPerRequest ( row )
                #if counter == 2 : sys.exit(0)
                if row_status  == False  : continue
                filtered_data_list.append ( row )

            ## for final formatting get the max length of the fields
            for row_col_index , row_col_data in enumerate ( row ) : ##
                col_name = self.getCol4Index ( row_col_index )
                #print col_name, row_col_index, row_col_data
                col_max_field_length = self.getColFieldMaxLength ( col_name )
                if col_max_field_length < len(row_col_data) :
                    self.setColFieldMaxLength ( col_name, len(row_col_data)  )

        if self.options.match_pattern is not None or self.options.expr is not None :
            self.data_list = filtered_data_list

        self.getTopLastRowPerRequest ( )

        self.getSortedDataPerRequest ( )

        self.performDataStats ( )

        if self.options.smartdisplay == True :
            self.formatForSmartDisplay ( )

        return

    def performDataStats ( self ) :

        if self.options.showstats == False and self.options.showonlystats == False : return

        self.data_list = self.transposed ( self.data_list )

        for rownum, row  in enumerate ( self.data_list ) :

            col_name = self.getCol4Index ( rownum )
            max_field_length = self.getColFieldMaxLength ( col_name )

            stats_n = 0
            stats_pos_n = 0
            stats_neg_n = 0
            stats_zero_n = 0
            stats_min = 0
            stats_max = 0
            stats_sum = 0
            stats_median = 0
            stats_mean = 0
            stats_abs_mean = 0
            stats_var = 0
            stats_stddev = 0
            stats_tstat = 0
            stats_sharpe = 0
            stats_abs_sum = 0

            try :

                data_row_process = list()
                try :
                    data_row_process = [ float(x) for x in row ]
                    data_row_process.sort()
                except :
                    pass

                if self.options.showonlystats == True : row = list()

                row.append ( '====' )

                stats = Statistics( data_row_process )

                stats_n =  niceNum ( stats.N )
                stats_n = "NUM:" + str(stats_n)
                if max_field_length < len(stats_n) : max_field_length = len(stats_n)

                stats_pos_n = niceNum ( stats.posN )
                stats_pos_n = "PNUM:" + str(stats_pos_n )
                if max_field_length < len(stats_pos_n) : max_field_length = len(stats_pos_n)

                stats_neg_n = niceNum ( stats.negN )
                stats_neg_n = "NNUM:" + str(stats_neg_n )
                if max_field_length < len(stats_neg_n) : max_field_length = len(stats_neg_n)

                stats_zero_n = niceNum ( stats.zeroN )
                stats_zero_n = "ZNUM:" + str(stats_zero_n )
                if max_field_length < len(stats_zero_n) : max_field_length = len(stats_zero_n)

                stats_min =  niceNum ( stats.min )
                stats_min = "MIN:" + str(stats_min)
                if max_field_length < len(stats_min) : max_field_length = len(stats_min)

                stats_max =  niceNum ( stats.max )
                stats_max = "MAX:" + str(stats_max)
                if max_field_length < len(stats_max) : max_field_length = len(stats_max)

                stats_sum =  niceNum ( stats.sum )
                stats_sum = "SUM:" + str(stats_sum)
                if max_field_length < len(stats_sum) : max_field_length = len(stats_sum)

                stats_mean =  niceNum ( stats.mean )
                stats_mean = "AVG:" + str(stats_mean)
                if max_field_length < len(stats_mean) : max_field_length = len(stats_mean)

                stats_abs_mean =  niceNum ( stats.absmean )
                stats_abs_mean = "ABAVG:" + str(stats_abs_mean)
                if max_field_length < len(stats_abs_mean) : max_field_length = len(stats_abs_mean)

                stats_abs_sum =  niceNum ( stats.abssum )
                stats_abs_sum = "ABSUM:" + str(stats_abs_sum)
                if max_field_length < len(stats_abs_sum) : max_field_length = len(stats_abs_sum)

                stats_median =  niceNum ( stats.median )
                stats_median = "MED:" + str(stats_median)
                if max_field_length < len(stats_median) : max_field_length = len(stats_median)

                stats_var =  niceNum ( stats.variance )
                stats_var = "VAR:" + str(stats_var)
                if max_field_length < len(stats_var) : max_field_length = len(stats_var)

                stats_stddev =  niceNum ( stats.stddev )
                stats_stddev = "STD:" + str(stats_stddev)
                if max_field_length < len(stats_stddev) : max_field_length = len(stats_stddev)

                stats_tstat = niceNum(stats.tstat )
                stats_tstat = "TSTAT:" + str(stats_tstat)
                if max_field_length < len(stats_tstat) : max_field_length = len(stats_tstat)

                stats_sharpe = niceNum(stats.sharpe )
                stats_sharpe = "SHRP:" + str(stats_sharpe)
                if max_field_length < len(stats_sharpe) : max_field_length = len(stats_sharpe)

                row.append ( stats_n )
                row.append ( stats_pos_n )
                row.append ( stats_neg_n )
                row.append ( stats_zero_n )
                row.append ( stats_min )
                row.append ( stats_max )
                row.append ( stats_sum )
                row.append ( stats_mean )
                row.append ( stats_abs_mean )
                row.append ( stats_abs_sum )
                row.append ( stats_median )
                row.append ( stats_var )
                row.append ( stats_stddev )
                row.append ( stats_tstat )
                row.append ( stats_sharpe )

            except Exception as msg :

                row.append ( stats_n )
                row.append ( stats_pos_n )
                row.append ( stats_neg_n )
                row.append ( stats_zero_n )
                row.append ( stats_min )
                row.append ( stats_max )
                row.append ( stats_sum )
                row.append ( stats_mean )
                row.append ( stats_abs_mean )
                row.append ( stats_abs_sum )
                row.append ( stats_median )
                row.append ( stats_var )
                row.append ( stats_stddev )
                row.append ( stats_tstat )
                row.append ( stats_sharpe )

            if self.options.showonlystats == True : self.data_list[rownum] = row[:]

            if max_field_length > self.getColFieldMaxLength ( col_name )  :
                self.setColFieldMaxLength ( col_name, max_field_length )


        self.data_list = self.transposed ( self.data_list )


    def convertColumnsToNumeric ( self, sort_col_index ) :

        if len(sort_col_index) > 0 :
            for row in self.data_list :
                for i  in sort_col_index :
                    try :
                        row[i] = Decimal ( row[i] )
                    except :
                        pass


    def getSortedDataPerRequest ( self ) :

        if self.options.sortcol is None and self.options.rsortcol is None : return

        if self.options.sortcol != None :
            sort_col_list = self.options.sortcol.split(",")
            reverse_flag = False
        if self.options.rsortcol != None :
            sort_col_list = self.options.rsortcol.split(",")
            reverse_flag = True

        sort_col_index = [ self.getIndex4Col(col) for col in sort_col_list  ]

        if len(sort_col_index) >= 3 : sort_col_index  = sort_col_index[0:3]

        if len(sort_col_list) == 1 :
            if self.options.sorttype == "numeric" : self.convertColumnsToNumeric ( sort_col_index )
            self.data_list = sorted ( self.data_list, key = itemgetter( sort_col_index[0] ), reverse = reverse_flag )
        elif len(sort_col_list) == 2 :
            if self.options.sorttype == "numeric" : self.convertColumnsToNumeric ( sort_col_index )
            self.data_list = sorted ( self.data_list, key = itemgetter( sort_col_index[0], sort_col_index[1] ), reverse = reverse_flag )
        elif len(sort_col_list) == 3 :
            if self.options.sorttype == "numeric" : self.convertColumnsToNumeric ( sort_col_index )
            self.data_list = sorted ( self.data_list, key = itemgetter( sort_col_index[0], sort_col_index[1], sort_col_index[2] ), reverse = reverse_flag )

        return


    def getTopLastRowPerRequest ( self ) :

        top_row_request = int(self.options.top)
        last_row_request = int(self.options.last)

        if top_row_request <= 0 and last_row_request <= 0 : return

        if ( top_row_request + last_row_request ) >= len(self.data_list) : return

        top_data_list     = list()
        last_data_list  = list()

        if int(self.options.top) > 0 and  len(self.data_list) > int(self.options.top) :
            top_data_list  = self.data_list[0:int(self.options.top)]
        if int(self.options.last) > 0 and len(self.data_list) > int(self.options.last) :
            last_data_list = self.data_list[-1 * int(self.options.last):]

        self.data_list = top_data_list + last_data_list

        return

    def transposed( self, lists ):

        if not lists: return []
        return list(map(lambda *row: list(row), *lists))


    def displayTransposeResults ( self ) :

        disply_cols_list = list()
        if self.options.cols is None :
            if self.options.showfilename == False and self.options.showfiledate == False :
                display_cols_list = self.header_list[1:]
            else :
                display_cols_list = self.header_list[:]
        else :
            display_cols_list = self.options.cols.split(",")

        display_cols_list = [ col for col in display_cols_list if self.hasCol(col) == True ]

        if self.options.excols is not None : display_cols_list  = self.removeExcludeCols ( display_cols_list )

        index_display_cols_list       = [ self.getIndex4Col(col) for col in display_cols_list ]
        display_col_field_length_list = [ self.getColFieldMaxLength(col) for col in display_cols_list ]
        max_col_field_length = max ( display_col_field_length_list ) + 2

        self.data_list = self.transposed ( self.data_list )

        for i in index_display_cols_list :
            row = self.data_list[i]
            col_name = self.getCol4Index ( i )
            data_row = [ col_name ] +  row

            if self.options.bottom == True : data_row = data_row + [ col_name ]

            format_str  = self.getTransposeDataFormatter ( data_row , max_col_field_length )
            format_data = self.getTransposeData ( data_row )

            eval_str = r'"' + format_str + '"' + " % " + "( " +  format_data + " )"
            print(eval ( eval_str ))



    def displayVerticalResults ( self ) :

        disply_cols_list = list()
        if self.options.cols is None :
            if self.options.showfilename == False and self.options.showfiledate == False :
                display_cols_list = self.header_list[1:]
            else :
                display_cols_list = self.header_list[:]
        else :
            display_cols_list = self.options.cols.split(",")

        display_cols_list = [ col for col in display_cols_list if self.hasCol(col) == True ]

        if self.options.excols is not None : display_cols_list  = self.removeExcludeCols ( display_cols_list )

        index_display_cols_list       = [ self.getIndex4Col(col) for col in display_cols_list ]
        display_col_field_length_list = [ self.getColFieldMaxLength(col) for col in display_cols_list ]

        max_col_field_length = max ( display_col_field_length_list ) + 5

        for row in self.data_list :
            for i, col in enumerate ( display_cols_list ) :
                col_value = row[ index_display_cols_list[i] ]
                format_str = '"%' + str(max_col_field_length) + 's' + self.options.dispdelim + '%' + str(max_col_field_length) + 's"'
                format_data = r' ( ' + '"' + col + '"' + ',' + '"' +  str(col_value)  + '"' + ' ) '
                eval_str = format_str + " % " +  format_data
                print(eval ( eval_str ))
            print()

    def removeExcludeCols ( self, display_cols_list ) :

        for col in self.options.excols.split(","):
            if self.hasCol(col) : display_cols_list.remove ( col )
        return display_cols_list


    def displayResults ( self ) :

        disply_cols_list = list()
        if self.options.cols is None :
            if self.options.showfilename == False and self.options.showfiledate == False :
                display_cols_list = self.header_list[1:]
            else :
                display_cols_list = self.header_list[:]
        else :
            display_cols_list = self.options.cols.split(",")

        display_cols_list = [ col for col in display_cols_list if self.hasCol(col) == True ]

        if self.options.excols is not None : display_cols_list  = self.removeExcludeCols ( display_cols_list )

        index_display_cols_list       = [ self.getIndex4Col(col) for col in display_cols_list ]
        display_col_field_length_list = [ self.getColFieldMaxLength(col) for col in display_cols_list ]

        format_str    = self.getFieldsFormatter ( display_col_field_length_list )
        format_header = self.getDataHeaderFormatter ( display_cols_list )

        ## print the header
        eval_header_str = r'"' + format_str +  '"'  + " % " + "( " + format_header + " )"
        print(eval ( eval_header_str ))

        ## print each data line

        for counter, row in enumerate(self.data_list) :
            display_row_list = [ row[i] for i in  index_display_cols_list ]
            format_data = self.getDataHeaderFormatter ( display_row_list )

            eval_str = r'"' + format_str  + '"'  + " % " + "( " + format_data + " )"
            print(eval ( eval_str ))

            if self.options.dispmidheader == True and counter > 20 and ( counter % 20 ) == 0   :
                print(eval ( eval_header_str ))

        if self.options.bottom == True :
            eval_str = r'"' + format_str +  '"'  + " % " + "( " + format_header + " )"
            print(eval ( eval_str ))

        return

    def getFieldsFormatter ( self, display_col_field_length ) :

        if self.options.raw == True :
            format_str = self.options.dispdelim.join ( [ '%s' for i in display_col_field_length ] )
        else :
            format_str = self.options.dispdelim.join ( [ '%' + str(i+1) + 's' for i in display_col_field_length ] )
        return format_str


    def getTransposeDataFormatter ( self, data_row, max_col_field_length ) :

        format_str = self.options.dispdelim.join ( [ '%' + str(max_col_field_length) + 's' for i in data_row ] )
        return format_str

    def getTransposeData ( self, data_row ) :

        data_str =  ','.join( [ '"' + str(i) + '"' for i in data_row ] )
        return data_str

    def getDataHeaderFormatter ( self, display_cols_list ) :

        header_str = ','.join( [ '"' + str(i) + '"' for i in display_cols_list ] )
        return header_str

    def getDataFormatter ( self, display_row_list ) :

        data_str = ','.join( [ str(i) for i in display_row_list ] )
        return data_str


    def hasCol ( self, col ) :

        return  col in self.cols_dict

    def getIndex4Col ( self,  col ) :

        return self.cols_dict[col]

    def getCol4Index ( self, index ) :

        return self.header_list[index]

    def getColFieldMaxLength ( self, col ) :

        return self.cols_field_max_length_dict[col]

    def setColFieldMaxLength ( self, col, max_length ) :

        if col not in self.cols_field_max_length_dict :
            self.cols_field_max_length_dict[col] = max_length
        elif max_length > self.cols_field_max_length_dict[col] :
            self.cols_field_max_length_dict[col] = max_length


    def addExtraHeaderCol ( self, col ) :

        if self.hasCol ( col ) == False :
            self.header_list.append ( col )
            self.cols_dict[col]  = self.header_list.index ( col )
            self.cols_field_max_length_dict[col] = len(col)

    def formatForSmartDisplay ( self ) :

        cols_ignore_list = [ 'sid', 'date', 'file_name' , 'time' , 'file_date' ]
        cols_index_ignore = dict()
        for col in list(self.cols_dict.keys()):
            if col in cols_ignore_list:
                cols_index_ignore [ self.getIndex4Col(col) ] = col

        for counter, row in enumerate ( self.data_list ) :
            for row_col_index, row_col_data in enumerate ( row ) :
                if row_col_data != '' : row_col_data = str(row_col_data)
                if row_col_index in cols_index_ignore : continue
                if not re.search ( '[A-Z:=]', row_col_data, re.I ) and row_col_data != '' :
                    self.data_list[counter][row_col_index] = niceNum ( row_col_data ).strip()
        return



if __name__ == '__main__' :

    args = startUp()

    data_list   = list()
    header_list = list()
    buss_days   = list()

    try :

        if options.tailf is None :
            if len(args):
                files_processed = dict()
                if options.startdate != None and options.enddate != None :
                    bdObj = BusinessDays()
                    buss_days = bdObj.getBusinessDays ( options.startdate, options.enddate )
                for file_name in args :
                    if len(buss_days) != 0 :
                        for pdate in buss_days :
                            pfile_name = FileUtil.populateDateValues ( file_name, pdate )
                            if os.path.exists ( pfile_name ) == False : continue ## this file is absent. Ignore
                            if pfile_name in files_processed : continue ## this file was processed before. Ignore
                            files_processed[pfile_name] = 1
                            ( data_list, header_list ) = FileDataReader ( pfile_name, options ).processData ( data_list, header_list  )
                    else :
                        ( data_list, header_list ) = FileDataReader ( file_name, options  ).processData ( data_list, header_list )
            else :
                ( data_list, header_list ) = FileDataReader ( sys.stdin, options  ).processData ( data_list, header_list )

            if options.removeheaderspaces == True :
                for i, col in enumerate(header_list):
                    header_list[i] = re.sub ( ' ', '_', col )

            if options.cleanupheadercols == True :
                for i, col in enumerate(header_list):
                    header_list[i] = re.sub('[^0-9a-zA-Z]+', '_', col )

            tbObj = Table ( data_list, header_list , options  )

            tbObj.processDataPerRequest ( )

            #print

            # the last part is to display, this will have columns to disply and the transfose, head, tail
            if options.colsmatch is not None :
                tbObj.setColumnsToDisplayByMatch ( )

            if options.vertical == True :
                tbObj.displayVerticalResults()
            elif options.transpose == True :
                tbObj.displayTransposeResults()
            else :
                tbObj.displayResults ( )
        else : ## this is for realtime tail option on that file
            first_run = True
            file_name = args[0]
            fdlReadObj = FileDataReader ( file_name, options  )
            ( data_list, header_list ) = fdlReadObj.processData ( [], header_list )

            if options.removeheaderspaces == True :
                for i, col in enumerate(header_list):
                    header_list[i] = re.sub ( ' ', '_', col )

            tbObj = Table ( data_list, header_list , options  )

            while True :
                if first_run != True :
                    ( data_list, header_list ) = fdlReadObj.processData ( [], header_list )
                    tbObj.setDataList ( data_list )
                else :
                    first_run = False
                tbObj.processDataPerRequest ( )

                if len(data_list) != 0 :
                    tbObj.setDataList ( data_list )
                    tbObj.processDataPerRequest ( )
                    # the last part is to display, this will have columns to disply and the transfose, head, tail
                    if options.vertical == True :
                        tbObj.displayVerticalResults()
                    elif options.transpose == True :
                        tbObj.displayTransposeResults()
                    else :
                        tbObj.displayResults ( )
                    print()
                time.sleep(1)

    except Exception as e:
        exc_type, exc_obj, exc_tb = sys.exc_info()
        fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
        print(( fname, exc_tb.tb_lineno, sys.exc_info() ))




    sys.exit(0)
