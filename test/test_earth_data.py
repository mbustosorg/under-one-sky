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
from unittest import TestCase

import underonesky.earth_data.earth_data as ed


class TestEarthData(TestCase):

    def test_tide_level(self):
        """ Ensure level is valid """
        level = ed.moon_phase()
        self.assertLess(level, 9)
        self.assertGreater(level, 0)

    def test_sun(self):
        """ Ensure able to get solar data """
        sunset = ed.current_sunset()
        self.assertEqual(sunset.year, 2000)
