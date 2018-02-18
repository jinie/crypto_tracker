#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import time
from io import BytesIO
from pprint import pprint
import locale

import PIL
import inkyphat
import krakenex
import matplotlib
matplotlib.use('Agg')
import pandas as pd
import requests
from PIL import Image, ImageDraw, ImageFont
from pykrakenapi import KrakenAPI
from collections import defaultdict

import collections
import functools


class memoized(object):
    '''Decorator. Caches a function's return value each time it is called.
    If called later with the same arguments, the cached value is returned
    (not reevaluated).
    '''

    def __init__(self, func):
        self.func = func
        self.cache = {}

    def __call__(self, *args):
        if not isinstance(args, collections.Hashable):
            # uncacheable. a list, for instance.
            # better to not cache than blow up.
            return self.func(*args)
        if args in self.cache:
            return self.cache[args]
        else:
            value = self.func(*args)
            self.cache[args] = value
            return value

    def __repr__(self):
        '''Return the function's docstring.'''
        return self.func.__doc__

    def __get__(self, obj, objtype):
        '''Support instance methods.'''
        return functools.partial(self.__call__, obj)

class Config(object):
    def __init__(self, filename):
        with open(filename, 'rt') as f:
            conf = json.loads(f.read())
            for k,v in conf.items():
                setattr(self, k, v)

    def get_currencies(self):
        return {
            'XRP': XrpHandler(),
            'ETH': EthHandler(),
            'XBT': XbtHandler(),
            'LTC': LtcHandler(),
        }

class CurrencyHandler(object):
    '''Handler base class for a crypto currency'''
    def __init__(self, config):
        self.config = config
        self._fiat_currency = config.fiat_currency

    def update(self, accounts):
        raise Exception('Not implemented')

    @memoized
    def get_logo_image(self,url):
        try:
            req = requests.get(url)
            image = BytesIO(req.content)
            img = PIL.Image.open(image)
            img = img.convert('P')
            img.putpalette((0, 0, 0, 255, 255, 255, 255, 0, 0) + (0, 0, 0)*252)
            img.thumbnail((70, 104))
            return img
        except:
            return None

    def logo(self):
        return None

    def fiat_currency(self):
        return self._fiat_currency


class LtcHandler(CurrencyHandler):

    def update(self, accounts):
        total = 0
        for act in accounts:
            url = 'https://api.blockcypher.com/v1/ltc/main/addrs/{}'.format(
                act)
            req = requests.get(url)
            balance = json.loads(req.text)
            if 'final_balance' in balance:
                total += balance['final_balance']
        return total / 100000000

    def logo(self):
        return self.get_logo_image('http://ltc.133.io/images/logosizes/ltc800.png')


class XbtHandler(CurrencyHandler):

    def update(self, accounts):
        url = 'https://www.blockonomics.co/api/balance'
        addrs = ""
        for a in accounts:
            addrs += a + " "
        body = json.dumps({'addr': addrs})
        req = requests.post(url, data=body)
        balances = json.loads(req.text)
        total = 0
        if 'response' not in balances:
            pprint(balances)
            return 0
        for act in balances['response']:
            total += act['confirmed']
        return total/100000000

    def logo(self):
        return self.get_logo_image('https://bitcoin.org/img/icons/opengraph.png')


class XrpHandler(CurrencyHandler):

    def update(self, accounts):
        total = 0
        for account in accounts:
            url = "https://data.ripple.com/v2/accounts/{}/balances".format(
                account)
            req = requests.get(url)
            balances = json.loads(req.text)
            for b in balances['balances']:
                if b['currency'] == 'XRP':
                    total += float(b['value'])
        return total

    def logo(self):
        return self.get_logo_image('https://www.shareicon.net/data/512x512/2016/07/08/117527_ripple_512x512.png')


class EthHandler(CurrencyHandler):

    def update(self, accounts):
        total = 0
        for act in accounts:
            url = 'https://api.ethplorer.io/getAddressInfo/{}?apiKey=freekey'.format(
                act)
            req = requests.get(url)
            balances = json.loads(req.text)
            total += balances['ETH']['balance']
        return total

    def logo(self):
        return self.get_logo_image('https://www.ethereum.org/images/logos/ETHEREUM-ICON_Black_small.png')


class CryptoTracker(object):

    def __init__(self,config):
        api = krakenex.API()
        self.k = KrakenAPI(api)
        self.config = config

    def get_exchange_rate(self, crypto, fiat):
        pair = "X{}Z{}".format(crypto, fiat)
        ticker = self.k.get_ticker_information(pair)
        return ticker

    def get_currencies(self):
        return {
            'XRP': XrpHandler(self.config),
            'ETH': EthHandler(self.config),
            'XBT': XbtHandler(self.config),
            'LTC': LtcHandler(self.config),
        }

    def get_local_currency(self):
        return self.config.local_currency

    def get_fiat_currency(self):
        return self.config.fiat_currency

    def get_exchange_rates(self, base=None):
        url = 'https://api.fixer.io/latest'
        if base is not None:
            url += '?base={}'.format(base)
        req = requests.get(url)

        rates = json.loads(req.text)
        return rates['rates']

    def update_currencies(self):
        accounts = self.config.accounts

        balances = defaultdict(float)
        rates = defaultdict(float)
        crypto_currencies = self.get_currencies()

        for curr in accounts.keys():
            ohlc = self.get_exchange_rate(curr, crypto_currencies[curr].fiat_currency())
            if ohlc is not None and len(ohlc) > 0:
                rates[curr] = float(ohlc.iloc[0]['c'][0])
            balances[curr] += crypto_currencies[curr].update(accounts[curr])
        positions = {curr: balances[curr] * rates[curr] for curr in balances if curr in rates and curr in balances}
        return balances, positions


class DisplayHandler(object):

    def __init__(self, config, cryptotracker):
        locale.setlocale(locale.LC_ALL, '')
        self.cryptotracker = cryptotracker
        self.config = config

    def cga_quantize(self, image):
        pal_image = Image.new("P", (1, 1))
        pal_image.putpalette(
            (0, 0, 0, 255, 0, 0, 255, 255, 255) + (0, 0, 0)*252)
        return image.convert("RGB").quantize(palette=pal_image)

    def ax_to_image(self, ax):
        buf = BytesIO()
        fig = ax.get_figure()
        fig.savefig(buf, format='png', dpi=fig.dpi, bbox_inches='tight')
        im = Image.new('RGB', (inkyphat.WIDTH, inkyphat.HEIGHT),
                       (255, 255, 255))
        pi = Image.open(buf)
        pi.thumbnail((inkyphat.WIDTH, inkyphat.HEIGHT))
        w, h = pi.size
        xo = (inkyphat.WIDTH - w)//2
        yo = (inkyphat.HEIGHT - h)//2
        im.paste(pi, (xo, yo), pi)
        return self.cga_quantize(im)

    def get_position_image(self, positions):
        v = pd.Series(positions)
        plot = v.plot(kind='bar', figsize=(2.3, 1), fontsize=13, color=['r', ])
        plot.set_facecolor('w')
        x_axis = plot.axes.get_yaxis()
        x_axis.set_visible(False)
        return self.ax_to_image(plot)

    def create_image(self, logo, lines):
        im = Image.new("P", (inkyphat.WIDTH, inkyphat.HEIGHT), 255)
        im.putpalette(((0, 0, 0, 255, 0, 0, 255, 255, 255) + (0, 0, 0)*252))
        draw = ImageDraw.Draw(im)
        draw.rectangle((0, 0, inkyphat.WIDTH, inkyphat.HEIGHT),
                       fill='white', outline='white')
        x_offset = 0
        if logo is not None:
            logo = self.cga_quantize(logo)
            w, h = logo.size
            ypos = (inkyphat.HEIGHT - h)//2
            im.paste(logo, (0, ypos))
            x_offset = 71

        max_fontsize = (inkyphat.HEIGHT-len(lines)) // len(lines) 
        y_offset = (inkyphat.HEIGHT - (max_fontsize * len(lines))) // 2
        for text in lines:
            fontsize = max_fontsize
            fits = False
            while not fits and fontsize > 5:
                font = ImageFont.truetype(inkyphat.fonts.FredokaOne, fontsize)
                w, h = font.getsize(text)
                if w < inkyphat.WIDTH - x_offset:
                    fits = True
                else:
                    fontsize -= 1
            draw.text((x_offset, y_offset), text, (255, 0, 0), font=font)
            y_offset += fontsize + 1
        return im

    def get_24hour_value(self, current_value, balances):
        since = time.time() - 60*60*24
        old_value = 0
        crypto_currencies = self.cryptotracker.get_currencies()
        for curr in balances.keys():
            ch = crypto_currencies[curr]
            if balances[curr] <= 0:
                continue
            oh = self.cryptotracker.k.get_ohlc_data('X{}Z{}'.format(curr, ch.fiat_currency()), interval=5, since=since, ascending=True)
            old_value += balances[curr] * oh[0]['close'][-1]

        change = current_value - old_value
        return (100/old_value)*change

    def standing_images(self):
        balances, values = self.cryptotracker.update_currencies()
        rates = self.cryptotracker.get_exchange_rates()
        crypto_currencies = self.cryptotracker.get_currencies()
        local_currency = self.cryptotracker.get_local_currency()
        local_total = round(sum(values.values()), 2) * \
            rates[self.cryptotracker.get_local_currency()]
        yield self.get_position_image(values)
        yield self.create_image(None, lines=['Total Holdings', locale.currency(local_total, grouping=True, symbol=True, international=True),'24 Hour change', '{} %'.format(round(self.get_24hour_value(sum(values.values()), balances)), 2)])
        for curr in balances.keys():
            total = round(values[curr]*rates[local_currency], 2)
            yield self.create_image(crypto_currencies[curr].logo(), (curr, str(balances[curr]), locale.currency(total, symbol=True, grouping=True, international=True)))


    def show_slideshow(self, delay=30):
        for image in self.standing_images():
            inkyphat.set_image(image)
            inkyphat.show()
            time.sleep(delay)


def main():
    config = Config('config.json')
    tracker = CryptoTracker(config)
    display = DisplayHandler(config, tracker)
    while True:
        display.show_slideshow()

if __name__ == '__main__':
    main()
