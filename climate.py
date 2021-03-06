#!/usr/bin/env python
# coding=utf-8

from __future__ import unicode_literals
import calendar
import json
import sys
from collections import OrderedDict
import urllib

import astrodata
import cache

timer = []

# hardcode rather than using calendar.month_abbr to avoid 
# potential locale problems - wikipedia always uses the English abbrs
MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
NUM_MONTHS = len(MONTHS)

ROWS = ['record high C', 'high C', 'mean C', 'low C', 'record low C', 'sun', 
    'precipitation days', 'precipitation mm',
    'rain days', 'rain mm', 'snow days', 'snow cm']
# TODO: add support for other data of interest

PRINTED_ROW_TITLES = {'record high C': 'r-high', 'high C': 'high',
    'mean C': 'mean', 'low C': 'low', 'record low C': 'r-low', 'sun': 'sun',
    'precipitation days': 'prep days', 'precipitation mm': 'prep mm',
    'rain days': 'rain days', 'rain mm': 'rain mm',
    'snow days': 'snow days', 'snow cm': 'snow cm'}

ROWS_TO_PRINT = ['record high C', 'high C', 'low C', 'record low C', 'sun']
# , 'snow days', 'snow cm', 'precipitation days', 'precipitation mm', 'rain days', 'rain mm']

MSG_LOCATION_NOT_FOUND  = ': location not found'
MSG_NO_INFO_FOUND       = ': no information found'

UNIT_CONVERSIONS = {
    'F': {
        'C': (lambda f: round((f - 32)*(5.0/9.0), 1))
    },
    'inch': {
        'mm': (lambda x: round(x*25.4, 1)),
        'cm': (lambda x: round(x*2.54, 1))
    },
    'mm': { 'cm': (lambda x: x*10) },
    'cm': { 'mm': (lambda x: x/10.0) }
    }

ABSOLUTE_ROWS = ['sun', 'snow days', 'snow cm', 'rain days', 'rain mm',
    'precipitation days', 'precipitation mm']

API_URL = 'http://en.wikipedia.org/w/api.php?action=query&prop=revisions&titles=%s&redirects=true&rvprop=content&format=json'

def get_page_source(page_name):
    url = API_URL % urllib.quote_plus(page_name.encode('utf-8'))
    text = cache.get_URL(url, page_name)
    data = json.loads(text)

    try:
        page = data['query']['pages'].itervalues().next()
        page_title = page['title']
    except:
        return 'unknown error occurred',False

    try:
        # this line will error for a non-existent page
        page_text = page['revisions'][0]['*']
    
        return page_title,page_text
    except:
        return unicode(page_name) + MSG_LOCATION_NOT_FOUND,False

def find_template(data, templateName):
    if data is False:
        return ''

    if not templateName.startswith('{{'):
        templateName = '{{' + templateName

    index1 = data.find(templateName)

    if index1 > -1:
        # there's a weather box - find its extent

        index2 = index1
        loop_end = False

        while not loop_end:
            # count template open and close tags to grab
            # full extent of weatherbox template.
            # avoids incomplete data due to cite or convert
            # templates.
            prev_index2 = index2

            index2 = data.find('}}', index2)+2
            open_count = data[index1:index2].count('{{') 
            clos_count = data[index1:index2].count('}}')

            # to end loop, check for two things:
            # - open count = close count: we found the 
            # complete template, can stop looking
            # - previous index is same as current index:
            # loop is not advancing, might be a malformed
            # page, avoid endless loop by breaking

            loop_end = (open_count == clos_count) and \
                (index2 != prev_index2) # do..while

        return data[index1:index2]
    else:
        return ''

def get_cities():
    cities = []

    # cgi arguments commented out because i have no way of testing them 
    # right now - don't want anything potentially shaky in live code
    """arguments = cgi.FieldStorage()

    if 'city' in arguments:
        cities = [unicode(arguments['city'].value)]
    elif 'cities' in arguments:
        cities = unicode(arguments['cities'].value).split(';')
    el"""
    if len(sys.argv) > 1:
        cities = sys.argv[1:]
        
    cities = [arg.decode('utf-8') for arg in cities]

    return cities

def remove_comments(text):
    # thanks, random wikipedians who put comments in the infobox
    if '<!--' in text:
        # first the first pair of <!-- comment tags -->
        start = text.find('<!--')
        end = text.find('-->')

        if end > start:
            # remove the comment between tags from text
            text = text[:start] + text[end+3:]

            # repeat until there are no comments left
            return remove_comments(text)
    else:
        return text

def parse_infobox(infobox):
    if infobox == '':
        # if not found, return early
        return {}

    # remove all comments (<!-- -->) from provided text.
    # wikipedians have increasingly used them within templates,
    # including spanning template sections, so we need to remove them 
    # before doing any processing.
    infobox = remove_comments(infobox)

    # Search through text to find things formatted like
    # [[Vancouver International Airport|YVR]]
    # as this would break splitting the template on "|".
    # Cut out the "|YVR" part to simplify.

    index = infobox.find('[[')
    while index > -1:
        index_of_end_of_link = infobox.find(']]', index)
        index_of_pipe = infobox.find('|', index)

        if -1 < index_of_pipe < index_of_end_of_link:
            infobox = infobox[:index_of_pipe] + infobox[index_of_end_of_link:]

        index = infobox.find('[[', index + 2)

    # split into template sections as specified by MediaWiki
    infobox_items = infobox.split('|')

    def process(item):
        line_data = item.split('=')

        key = line_data[0].strip()
        value = ''.join(line_data[1:]).strip()

        return key, value

    # Currently infobox_data has to be an OrderedDict because older code
    # expects to iterate through the infobox in year order. This worked
    # previously because all infoboxes I've worked with had data specified in
    # year order.
    # TODO: we should move code using this function to explicitly re-order data
    # it processes so that it is January to December, rather than depending
    # on Wikipedia wikisource to be in the correct order.
    infobox_data = OrderedDict(process(item) for item in infobox_items)
    infobox_data = OrderedDict((key, value) for (key, value) in infobox_data.items()
                               if value != '')

    return infobox_data

def get_coordinates(place):
    result = {'page_error': False}
    result['title'],page_data = get_page_source(place)

    infobox = find_template(page_data, 'Infobox settlement')
    data = parse_infobox(infobox)

    lat = 0
    lng = 0

    if 'latd' in data and 'longd' in data:
        # Infobox settlement has lat/long data, so parse that

        lat = float(data['latd'])
        if 'latm' in data:
            lat += float(data['latm']) / 60
        if 'lats' in data:
            lat += float(data['lats']) / 3600
        if 'latNS' in data and data['latNS'].lower() == 's':
            lat *= -1

        lng = float(data['longd'])
        if 'longm' in data:
            lng += float(data['longm']) / 60
        if 'longs' in data:
            lng += float(data['longs']) / 3600
        if 'longEW' in data and data['longEW'].lower() == 'w':
            lng *= -1

    elif lat == lng == 0:
        # no data found, look for one other template.
        # annoyingly there are four possible formats:
        # https://en.wikipedia.org/wiki/Template:Coord#Usage

        def index_or_minus_one(haystack, needle):
            try:
                return haystack.index(needle)
            except ValueError:
                return -1

        coords = find_template(page_data, 'Coord').strip()
        coords = coords.split('|')

        if len(coords):
            end_of_latitude = max(index_or_minus_one(coords, 'N'), index_or_minus_one(coords, 'S'))
            end_of_longitude = max(index_or_minus_one(coords, 'E'), index_or_minus_one(coords, 'W'))

            if end_of_latitude == end_of_longitude == -1:
                # in this format, the values are verbatim early on
                lat = float(coords[1])
                lng = float(coords[2])
            else:
                scan_index = 1
                lat_depth = 0
                lng_depth = 0

                while scan_index < end_of_latitude:
                    lat += float(coords[scan_index]) / 60**lat_depth

                    lat_depth += 1
                    scan_index += 1

                if coords[end_of_latitude] == 'S':
                    lat *= -1

                scan_index += 1  # skip latitude direction sign

                while scan_index < end_of_longitude:
                    lng += float(coords[scan_index]) / 60**lng_depth

                    lng_depth += 1
                    scan_index += 1

                if coords[end_of_longitude] == 'W':
                    lng *= -1

    lat = round(lat, 4)
    lng = round(lng, 4)

    result = { 'lat': lat, 'lng': lng }

    try:
        # on the other hand, elevation must be specified as a float
        if 'elevation_m' in data:
            result['elevation'] = float(data['elevation_m'])

        # also try to use max elevation and min elevation, in that order
        # TODO: might want to also try convert elevation_f
        if not 'elevation' in result and 'elevation_max_m' in data:
            result['elevation'] = float(data['elevation_max_m'])

        if not 'elevation' in result and 'elevation_min_m' in data:
            result['elevation'] = float(data['elevation_min_m'])
    except:
        # ignore: might be in a format float can't handle
        # (e.g. Whitehorse uses "670&ndash;1702")
        pass

    return result

def get_climate_data(place):
    def find_separate_weatherbox_template(data):
        if data is False:
            return ''

        # {{cityname weatherbox}} seems to be the usual template name.
        # I'll just look for any template ending with weatherbox.
        # I've not seen a page this breaks on yet.

        # New York City includes its weatherbox through a reference 
        # to {{New York City weatherbox/cached}}, where the /cached 
        # template contains rendered HTML tables. I want to look at 
        # "Template:New York City weatherbox" instead. Not sure how 
        # common this is, but NYC is pretty major and handling it
        # is easy, so might as well.
        index2 = max(data.find('weatherbox}}'),
            data.find('weatherbox/cached}}'),
            data.find('weatherbox|collapsed=Y}}'))

        if index2 > -1:
            # there is separate template - get it and process it
            index1 = data.rfind('{{', 0, index2)
            template_name = 'Template:' + data[index1+2:index2+10]

            weatherbox_title,data = get_page_source(template_name)
            if data is not False:
                return find_template(data, 'Weather box')

        # if we didn't find template, or we couldn't get it, fall back
        return ''

    def parse(text):
        text = text.strip().replace('−', '-')
        text = text.strip().replace('&minus;', '-')
        if text == '-':
            # used on some pages to indicate a no data condition
            return None
        if text == 'trace':
            # used on some pages to indicate essentially 0, I guess
            return 0

        return float(text)

    def month_number(month):
        # convert text month to number
        return MONTHS.index(month) + 1

    def daily_to_monthly(daily, month):
        month = month_number(month)

        # use a non-leap year since I suspect monthly numbers are given
        # for non-leap Februarys
        days = calendar.monthrange(2013, month)[1]

        return daily * days


    result = {'page_error': False}
    for row_name in ROWS:
        result[row_name] = []

    result['title'],data = get_page_source(place)

    if data is False:
        # indicates a problem getting data - signal it so output
        # can be formatted accordingly
        result['page_error'] = True
        return result

    weatherbox = find_template(data, 'Weather box')
    weatherbox_info = parse_infobox(weatherbox)

    if len(weatherbox_info) == 0:
        # weatherbox not found directly on page
        # see there's a dedicated city weather template we can look at
        weatherbox = find_separate_weatherbox_template(data).strip()
        weatherbox_info = parse_infobox(weatherbox)

    for key in weatherbox_info:
        value = weatherbox_info[key]

        # try to parse out location data - usually specifies a neighbourhood,
        # weather station, year range info, etc
        if key == 'location':
            # trim off wikilink markers, the most common
            # wiki syntax in this field
            result['location'] = value.replace('[', '').replace(']', '')

        month = key[:3]
        if month in MONTHS:
            category = key[3:].strip()  # take out the month to get data category
            value = parse(value)  # parse value as number

            # last token of category name is sometimes the unit
            # (C, F, mm, inch, etc)
            unit = category.rsplit(None, 1)[-1]

            if category in result:
                # straightforward putting the data in
                result[category].append(value)

            elif unit in UNIT_CONVERSIONS:
                # try to convert units to known ones
                for target_unit in UNIT_CONVERSIONS[unit]:
                    # try to find a category we collect that 
                    # we know how to convert into
                    converted_category = category.replace(unit, target_unit)
                    if converted_category in result:
                        converted = UNIT_CONVERSIONS[unit][target_unit](value)
                        result[converted_category].append(converted)
                        break

            elif category == 'd sun':
                # special handling for daily sun hours
                value = daily_to_monthly(value, month)
                result['sun'].append(value)

            # Process percentsun if present and we haven't found any other sun data.
            # Assume specific hour count is more precise than "% sunshine", so only
            # use percentsun if other data is not more available.
            # TODO: if percentsun is ahead of sun in the template, this
            # precautionary condition will still fail
            elif category == 'percentsun' and len(result['sun']) == 0:
                if 'observer' not in result:
                    location = result['title']
                   
                    # will try to get lat,lng from wikipedia page if location
                    # is not recognized by pyephem directly    
                    result['observer'] = astrodata.process_location(location)

                if result['observer'] != False:
                    daylight = astrodata.month_daylight(
                        result['observer'], month_number(month))
                    sun = (daylight.total_seconds()  / 3600) * (value /100)
                    sun = round(sun, 1)
                    result['sun'].append(sun)

    return result

def get_comparison_data(places, months, categories):
    """ Return data for a number of places, categories, and months.
     Takes a list of place names, list of 12 boolean values where True
    means the month is requested, and a dictionary of categoryname=boolean
    pairs (True means the category is requested) and returns the data as 
    long as it exists. Return data format is
    dict(month: dict(city: dict(category: data))) """

    data = {}
    for place in places:
        place_data = get_climate_data(place)

        if place_data['page_error'] is False:
            data[place_data['title']] = place_data

    result = {}
    for month,month_include in enumerate(months):
        if month_include:
            month_data = {}

            for place in data:
                place_data = {}

                for category,category_include in categories.items():
                    if category_include:
                        try:
                            # data might not contain info for the requested
                            # combination of place, category, and month. 
                            # if it doesn't, just pass by silently.
                            category_data = data[place][category][month]
                            place_data[category] = category_data
                        except:
                            # fail silently
                            pass

                month_data[place] = place_data

            result[month] = month_data

    return result

def has_printable_data(data):
    # This reflects the logic used in format_data_as_text(),
    # boiling it down to the minimum necessary to find out
    # if something will be printed. If format_data_as_text() 
    # is changed, this might need to be updated as well.

    has_data = False

    for row_name in PRINTED_ROW_TITLES:
        if row_name in data and len(data[row_name]) == NUM_MONTHS:
            has_data = True

    return has_data

def format_data_as_text(provided_data, print_all = False):
    if provided_data['page_error'] is True:
        # on page error, only print error message
        return provided_data['title']

    row_titles = dict((row,PRINTED_ROW_TITLES[row]) 
        for row in PRINTED_ROW_TITLES if row in ROWS_TO_PRINT or print_all)
    max_row_title = 0

    data = provided_data
    max_lengths = [0]*NUM_MONTHS

    for category in ROWS:
        if len(data[category]) == NUM_MONTHS \
            and isinstance(data[category][0], float):
            for i in range(NUM_MONTHS):
                data[category][i] = str(data[category][i])
                max_lengths[i] = max(max_lengths[i], len(data[category][i]))

            if category in row_titles:
                max_row_title = max(max_row_title, len(row_titles[category]))

    def format_one_row(row, title):
        # for categories holding absolute data like prep days, snow cm, etc
        # (rather than relative data like temperature or pressure),
        # print '0.0' as '-' or empty
        if title in ABSOLUTE_ROWS:
            row = [value if value != '0.0' else '-' for value in row]

        # pad row so all entries are right width for display
        row = [row[i].rjust(max_lengths[i]) for i in range(NUM_MONTHS)]

        result = row_titles[title].rjust(max_row_title) + '|'
        result = result + '|'.join(row) + '|'
        return result
    
    result = []
    for row_name in ROWS:
        if row_name in row_titles and row_name in data \
            and len(data[row_name]) == NUM_MONTHS:
            result.append(format_one_row(data[row_name], row_name))

    # add month indicators to top line
    # to make finding e.g. September easy
    month_names = format_one_row([month[0] for month in MONTHS], 'low C')
    
    title_length = len(data['title'])
    title_min_padding = 8

    title_padding = max(24, title_length + title_min_padding)

    if month_names[title_padding] == '|':
        # avoid having just a lone |
        title_padding += 1

    space_length = title_padding - title_length

    month_names = month_names[title_padding:]
    month_names = (' ' * space_length) + month_names

    if len(result) > 0:
        output = data['title'] + month_names + '\n'
        output = output + '\n'.join(result)

        if print_all and len(data['location']) > 0 \
            and data['title'] != data['location']:
            output = output + '\n' + data['location']
    else:
        output = data['title'] + MSG_NO_INFO_FOUND

    return output

def format_timer_info():
    output = ''

    if len(timer) > 0:
        output += '\n'.join(l[0] + ': ' + str(l[1]) for l in timer)

    if len(cache.timer) > 0:
        output += '\n'.join(l[0] + ': ' + str(l[1]) for l in cache.timer)

    return output

def parse_text_query(strings):
    """ Takes in an array of strings and extracts recognized months, 
    categories, and cities with climate data. Case- and order-insensitive,
    except city names must appear together.
    The logic used to try to stitch together multi-word city 
    Wikipedia article names (e.g. "Hamilton, New Zealand") is essentially 
    brute-force testing everything (so "Hamilton", "Hamilton New", 
    "Hamilton, New", "Hamilton New Zealand", "Hamilton New Zealand" until a 
    match is found or combinations are exhausted. Because of this, 
    the first lookup for a query with a long or unrecognized city name
    might take a while as we're sending a number of HTTP queries to Wikipedia.
    If caching is active, subsequent lookups should be near-instant. 
    However, if caching is not active, each lookup might be particularly slow 
    as the city-name-searching algorithm sends a number of queries and 
    the actual data retrieval makes further queries.
    So have caching on. (Or change the code.) """

    KEYWORDS = ['in', 'vs', 'versus', 'and', 'for']

    def city_has_data(city):
        data = get_climate_data(city)
        has_data = has_printable_data(data)

        return has_data

    result = {'cities': [], 'months': [], 'categories': []}

    result['months'] = [False]*12
    result['categories'] = dict((k,False) for k in ROWS)
    category_aliases = dict((v,k) for k,v in PRINTED_ROW_TITLES.iteritems())
    cities = []

    for param in strings:
        # classify each param
        param = param.decode('utf-8')

        classified = False

        # find months
        month_param = param.title()
        if month_param in calendar.month_abbr:
            month_number = list(calendar.month_abbr).index(month_param)
            result['months'][month_number - 1] = True
            classified = True
        if month_param in calendar.month_name:
            month_number = list(calendar.month_name).index(month_param)
            result['months'][month_number - 1] = True
            classified = True

        # find categories
        category_param = param.lower()
        if category_param in result['categories']:
            result['categories'][category_param] = True
            classified = True
        if category_param in category_aliases:
            result['categories'][category_aliases[category_param]] = True
            classified = True
        if category_param == 'location':
            result['categories']['location'] = True
            classified = True

        if classified is False and not param.lower() in KEYWORDS:
            cities.append(param)

    # find cities that we can find climate data for
    i = 0
    while i < len(cities):
        # first, try each string on its own
        city = cities[i].title()
        has_data = city_has_data(city)

        j = i
        while has_data == False and j < len(cities) - 1:
            # Single string was not recognized.
            # Try to build a page name we can recognize by adding in
            # strings that follow this one in the array

            # try using only spaces
            new_city = ' '.join(cities[i:j+2]).title()
            has_data = city_has_data(new_city)

            k = j+1
            while has_data == False and k < len(cities):
                # if just spaces didn't result in anything recognizable,
                # try using commas in any possible position
                new_city = ' '.join(cities[i:j+1]) + ', ' \
                    + ' '.join(cities[j+1:k+1])
                new_city = new_city.title()
                has_data = city_has_data(new_city)
                k += 1

            if has_data == True:
                city = new_city
                i = j + 1 # skip strings we've used this time
            else:
                j += 1 # look one more position further in the array

        if has_data == True:
            # we have a recognized city name, add it to the collection
            result['cities'].append(city)

        i += 1

    return result


if __name__ == '__main__':
    cities = get_cities()

    print_all_rows = '-a' in cities
    print_debug = '-t' in cities

    if print_all_rows:
        cities.remove('-a')
    if print_debug:
        cities.remove('-t')

    parsed_cities = parse_text_query(cities)['cities']

    if len(parsed_cities) > 0:
        print_cities = parsed_cities
    else:
        print_cities = cities

    for city in print_cities:
        data = get_climate_data(city)
        print format_data_as_text(data, print_all = print_all_rows)

    if print_debug:
        print format_timer_info()

