import pandas as pd
import datetime as dt
import numpy as np
from abc import abstractmethod, abstractproperty
from lxml import etree
import matplotlib.pyplot as plt
import datetime as dt
import urllib.request
import os.path
from bs4 import BeautifulSoup
#import seaborn as sns


class DataFetcher:

    def __init__(self, cache_path='cache.hdf5', verbose=False, only_cached=False):
        self._cache_path = cache_path
        self._only_cached = only_cached
        self._verbose = verbose
        self.download_cache_if_missing(cache_path)
        store = pd.HDFStore(self._cache_path)
        if '/urls' not in store.keys():
            store['urls'] = pd.DataFrame(columns=['url'])
        store.close()

    def download_cache_if_missing(self, cache_path):
        cache_url = 'https://kuleuven.box.com/shared/static/a52oz2boohn5ch1a18tau2tp6ee5cvtb.hdf5'
        if not os.path.isfile(cache_path):
            testfile = urllib.request.urlretrieve(cache_url, cache_path)


    def get_url(self, url, try_cache=True):
        df = None
        if try_cache:
            df = self.search_cache(url)
        if df is None and not self._only_cached:
            if self._verbose:
                print('fetching url:\t\t '+url)
            df = self.fetch_url(url)
            # save in store
            self.store_cache(url, df)
        elif self._verbose:
            #print('loaded from cache:\t '+url)
            pass
        return df

    @abstractmethod
    def fetch_url(self, url):
        pass

    def search_cache(self, url):
        df = None
        store = pd.HDFStore(self._cache_path)
        url_df = store['urls']
        filter = (url_df.url == url)
        if np.sum(filter) > 0:
            df = store['df'+str(url_df[filter].index[0])]
            np.sum(filter) > 0
        store.close()
        #print((toc-tic).microseconds/1000)
        return df

    def store_cache(self, url, df):
        store = pd.HDFStore(self._cache_path)
        url_df = store['urls']
        filter = (url_df.url == url)
        key = None
        if np.sum(filter)>0:
            # already exists, so get key
            key = url_df[filter].index[0]
        else:
            # create a new key
            key = url_df.index.size
            url_df.loc[key] = url
            store['urls'] = url_df
        # now save the df with the key
        store['df'+str(key)] = df
        store.close()


class EliaTotalLoadForecastFetcher(DataFetcher):

    def fetch(self):
        load_forecast_y = 'http://publications.elia.be/Publications/Publications/FileRepository.v1.svc/DownloadFile?filePath=\load_forecast\Total_load_forecast_{}.csv'
        now_year = dt.datetime.now().year
        years = np.arange(2014, now_year+1)
        dfs = []
        for i in range(years.size):
            year = years[i]
            url = load_forecast_y.format(str(years[i]))
            try_cache = (not now_year == year) or self._only_cached
            df = self.get_url(url, try_cache=try_cache)
            dfs.append(df)
        return pd.concat(dfs)

    def fetch_url(self, url):
        df_in = pd.read_csv(url)
        # remove nans
        # remove empty value rows
        filter_nan = np.logical_not(np.isnan(df_in.TotalLoadForecast))
        # remove rows where time has more than 5 characters
        filter_nan = np.logical_and(filter_nan, df_in.RowTime.str.len() == 5)
        df_in = df_in[filter_nan]
        df_in_timestamps = pd.to_datetime(df_in.RowDate + df_in.RowTime, format='%d/%m/%Y%H:%M')
        df_out = pd.DataFrame(
            data=df_in.TotalLoadForecast.values,
            index=df_in_timestamps,
            columns=['value'])
        return df_out


class ElexysBelpexFetcher(DataFetcher):

    @property
    def url(self):
        return 'https://my.elexys.be/MarketInformation/SpotBelpex.aspx'

    def fetch(self):
        # get last week from site
        df = self.fetch_url(self.url)
        # add cached values if present, and save again
        df = self.append_cache(df)
        return df

    def append_cache(self, df):
        df_old = self.search_cache(self.url)
        if df_old is not None:
            df = pd.concat([df, df_old])
            df = df[~df.index.duplicated('first')]
        self.store_cache(self.url, df)
        return df

    def save_stored_page_to_cache(self, file_path):
        with open(file_path, 'r') as f:
            data = f.read()
        df = self.parse_page_str(data)
        self.append_cache(df)

    def fetch_url(self, url):
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as response:
            data_str = response.read()
        return self.parse_page_str(data_str)

    def parse_page_str(self, str):
        soup = BeautifulSoup(str, 'lxml')
        rows = soup.find_all('tr', class_='dxgvDataRow_Office2010Blue')
        # skip first 4 and last row
        ts = []
        vals = []
        for row in rows:
            cells = row.find_all('td')
            timestamp = dt.datetime.strptime(cells[0].text, '%d/%m/%Y %H:%M:%S')
            val = float(cells[1].text[2:].replace('.', '').replace(',', '.'))
            ts.append(timestamp)
            vals.append(val)
        df = pd.DataFrame(data=dict(price=vals), index=ts)
        return df


class EliaAPIFetcher(DataFetcher):

    @property
    def api_url(self):
        pass

    def fetch(self, t_start=dt.datetime(year=2014, month=1, day=1), t_end=dt.datetime.now()):
        t_month = t_start.month
        t_year = t_start.year
        dfs = []
        t_start_fetch = dt.datetime(year=t_year, month=t_month, day=1)
        while t_start_fetch <= t_end:
            now = dt.datetime.now()-dt.timedelta(days=1)
            try_cache = not (now.month == t_month and now.year == t_year) or self._only_cached
            if t_month is 12:
                t_month = 1
                t_year += 1
            else:
                t_month += 1
            t_end_fetch = dt.datetime(year=t_year, month=t_month, day=1)
            url_start_end = self.api_url
            url = url_start_end.format(dt.datetime.strftime(t_start_fetch, '%Y-%m-%d'), dt.datetime.strftime(t_end_fetch, '%Y-%m-%d'))
            dfs.append(self.get_url(url, try_cache=try_cache))
            t_start_fetch = dt.datetime(year=t_year, month=t_month, day=1)
        df_out = pd.concat(dfs)
        # replace all -50 values with NaN, -50 is used to indicate that no value is available
        df_out = df_out.replace(-50, np.nan)
        return df_out

    def parse_root(self, root, NSP):
        pass

    def fetch_url(self, url):
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as response:
            data_str = response.read()
        root = etree.fromstring(data_str)
        NSP = '{' + root.nsmap[None] + '}'
        ts, cols = self.parse_root(root, NSP)
        df = pd.DataFrame(index=ts, data=cols)
        return df


class EliaSolarFetcher(EliaAPIFetcher):

    @property
    def api_url(self):
        return 'http://publications.elia.be/Publications/Publications/SolarForecasting.v4.svc/GetChartDataForZoneXml?dateFrom={}&dateTo={}&sourceId=1&_ga=2.68055058.2010966875.1521024315-1232406948.1519313643'

    def parse_root(self, root, NSP):
        ts = []
        cols = dict()
        cols['DayAheadForecast'] = []
        cols['WeekAheadForecast'] = []
        cols['MonitoredCapacity'] = []
        cols['LoadFactor'] = []
        cols['MostRecentForecast'] = []
        for item in root[2].iterfind(NSP+'SolarForecastingChartDataForZoneItem'):
            timestamp = dt.datetime.strptime(item.find(NSP + 'StartsOn')[0].text, '%Y-%m-%dT%H:%M:%SZ')
            ts.append(timestamp)
            for key in cols.keys():
                cols[key].append(float(item.find(NSP + key).text))
        return ts, cols


class EliaWindFetcher(EliaAPIFetcher):

    @property
    def api_url(self):
        return 'http://publications.elia.be/Publications/Publications/WindForecasting.v2.svc/GetForecastData?beginDate={}&endDate={}&isOffshore=&isEliaConnected=&_ga=2.68055058.2010966875.1521024315-1232406948.1519313643'

    def parse_root(self, root, NSP):
        ts = []
        cols = dict()
        cols['DayAheadForecast'] = []
        cols['DayAheadConfidence10'] = []
        cols['DayAheadConfidence90'] = []
        cols['WeekAheadConfidence10'] = []
        cols['WeekAheadConfidence90'] = []
        cols['MonitoredCapacity'] = []
        cols['LoadFactor'] = []
        cols['MostRecentForecast'] = []
        cols['Realtime'] = []
        for item in root[1].iterfind(NSP+'WindForecastingGraphItem'):
            timestamp = dt.datetime.strptime(item.find(NSP + 'StartsOn')[0].text, '%Y-%m-%dT%H:%M:%SZ')
            ts.append(timestamp)
            for key in cols.keys():
                value = item.find(NSP + key).text
                if value is not None:
                    value = float(value)
                else:
                    value = np.nan
                cols[key].append(value)
        return ts, cols

if __name__ == '__main__':
    while True:
        try:
            ew_fetcher = EliaWindFetcher(verbose=True, only_cached=False)
            wind = ew_fetcher.fetch()
            print('test')
        except Exception as e:
            pass
    test = ElexysBelpexFetcher()
    #test.save_stored_page_to_cache('elexys_all_until_2018_03_16.html')
    #test.save_stored_page_to_cache('price_all.html')
    price = test.fetch()
    price_index_all = pd.DatetimeIndex(start=price.index[-1], end=price.index[0], freq='1H')
    all = pd.DataFrame(index=price_index_all)
    all['hue'] = 'all'
    price['hue'] = 'price'
    pdc = pd.concat([all, price])
    pdc['val'] = 1
    pdc['x'] = pdc.index.year
    sns.boxplot(data=pdc, x='x', y='val', hue='hue')
    plt.show()
    etlf_fetcher = EliaTotalLoadForecastFetcher()
    load = etlf_fetcher.fetch()
    es_fetcher = EliaSolarFetcher()
    solar = es_fetcher.fetch()
    #plt.plot(solar.index, np.logical_not(np.isnan(solar.values)))
    #plt.legend(solar.columns)
    print('completed')