"""
    Copyright (C) 2020 Mauricio Bustos (m@bustos.org)
    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.
    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.
    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
import pandas as pd
import os
import datetime
from dateutil.relativedelta import relativedelta

phase_data = pd.read_csv(os.path.join(os.path.dirname(__file__), 'lunar_phases_phoenix.csv'), parse_dates=['DateTime']).set_index('DateTime')

sun_data = pd.read_csv(os.path.join(os.path.dirname(__file__), 'sunriseSunset.csv'), parse_dates=['sunrise', 'sunset'])
sun_data['sunrise'] = sun_data['sunrise'].apply(lambda x: x.tz_localize('UTC'))
sun_data['sunset'] = sun_data['sunset'].apply(lambda x: x.tz_localize('UTC'))
sun_data['date'] = sun_data['sunrise'].dt.date
sun_data = sun_data.set_index('date')

start_time = datetime.datetime.now()

PHASE_NAME = {
    1: "New Moon",
    2: "Waxing Crescent",
    3: "First Quarter",
    4: "Waxing Gibbous",
    5: "Full Moon",
    6: "Waning Gibbous",
    7: "Last Quarter",
    8: "Waning Crescent",
}


def moon_phase() -> int:
    """ Current tide level decile """
    return int(phase_data[phase_data.index > datetime.datetime.now()].iloc[0]['Phase'])


def current_sunset() -> pd.Timestamp:
    """ Current Sunset value """
    return sun_data.loc[datetime.datetime.utcnow().replace(year=2000).date()].loc['sunset']


def lights_out(on_offset: int, hard_off: str = None) -> bool:
    """ Are we off now? """
    now = pd.to_datetime(datetime.datetime.utcnow().replace(year=2000), utc=True).tz_convert('US/Arizona')
    on_delta = relativedelta(minutes=on_offset)
    sunrise = (sun_data.loc[now.date()]['sunrise'] + on_delta).tz_convert('US/Arizona')
    sunset = (sun_data.loc[now.date()]['sunset'] + on_delta).tz_convert('US/Arizona')
    if hard_off:
        off_time = pd.to_datetime(datetime.datetime.strptime(hard_off, '%H:%M')).tz_localize('US/Arizona')
        if now.time() > off_time.time():
            return True
    if sunrise < pd.to_datetime(now) < sunset:
        return True
    return False
