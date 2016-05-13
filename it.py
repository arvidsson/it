#!/usr/bin/python
from __future__ import division
import libtcodpy as libtcod
import random
from random import randint as roll
import math
import textwrap
#import shelve
import time
import os
#import multiprocessing
import cProfile as prof
import pstats
import copy
from collections import Counter, defaultdict, namedtuple
import itertools
import logging

import economy
import physics as phys
from traits import TRAITS, TRAIT_INFO, CULTURE_TRAIT_INFO, EXPERIENCE_PER_SKILL_LEVEL, MAX_SKILL_LEVEL
from dijkstra import Dijmap
import gen_languages as lang
import gen_creatures
import religion
import gui
import building_info
import combat
from helpers import *
import config as g
from wmap import *
from map_base import *
import history as hist
import goap
import data_importer as data


mouse = libtcod.Mouse()
key = libtcod.Key()


class Region:
    #a Region of the map and its properties
    def __init__(self, x, y):
        self.region = None
        self.x = x
        self.y = y
        self.color = None
        self.char = 255
        self.char_color = libtcod.black
        self.region_number = None # For figuring out play region

        self.agent_slots = {'land':{'slots':g.MAX_ECONOMY_AGENTS_PER_TILE, 'agents':[]}}

        self.blocks_mov = False
        self.blocks_vis = False

        self.res = defaultdict(int)
        self.entities = []
        self.populations = []
        self.objects = []

        self.features = []
        self.minor_sites = []
        self.caves = []

        self.all_sites = []

        self.associated_events = set([])

        self.height = 0
        self.temp = 0
        # self.rainfall = 0
        # old variables, hopefully to be removed!
        self.wdist = None
        self.moist = None

        self.region_number = None
        # Chunk will be set after region has been created
        self.chunk = None

        self.culture = None
        self.site = None
        self.territory = None
        self.explored = False

    def add_resource(self, resource_name, amount):
        self.res[resource_name] += amount
        self.agent_slots[resource_name] = {'slots':g.MAX_ECONOMY_AGENTS_PER_TILE, 'agents':[]}

        # Add location to to chunk of world this region is a part of
        self.chunk.resources[resource_name].append((self.x, self.y))

    def add_resource_gatherer_to_region(self, resource_name, agent):
        self.agent_slots[resource_name]['agents'].append(agent)
        agent.resource_gathering_region = self

        # Add farm only to places with resource gatherers
        if resource_name == 'land' and not self.has_minor_site(type_='farm'):
            g.WORLD.add_farm(self.x, self.y, city=self.territory)

        if resource_name in ('iron', 'bronze', 'copper') and not self.has_minor_site(type_='mine'):
            g.WORLD.add_mine(self.x, self.y, city=self.territory)

    def remove_resource_gatherer_from_region(self, resource_name, agent):
        self.agent_slots[resource_name]['agents'].remove(agent)
        agent.resource_gathering_region = None

        # In future, abandoning the farm
        #if resource_name == 'land' and self.has_minor_site(type_='farm') and not len(self.agent_slots['land']['agents']):
        #

    def has_open_slot(self, resource_name):
        ''' Return whether the list of agents working a particular resource is smaller than the limit for the total # of agents that can work it'''
        return resource_name in self.agent_slots and ( len(self.agent_slots[resource_name]['agents']) < self.agent_slots[resource_name]['slots'] )

    def clear_all_resources(self):
        self.res = defaultdict(int)

        self.agent_slots = {'land':{'slots':0, 'agents':[]}}

    def in_play_region(self):
        return g.WORLD.play_region == self.region_number

    def has_feature(self, type_):
        ''' Check if certain feature is in region '''
        for feature in self.features:
            if feature.type_ == type_:
                return 1

        return 0

    def has_minor_site(self, type_):
        ''' Check if certain feature is in region '''
        for site in self.minor_sites:
            if site.type_ == type_:
                return 1

        return 0

    def get_features(self, type_):
        ''' Returns a list of all features, so that one may get, say, all caves in the region '''
        feature_list = []
        for feature in self.features:
            if feature.type_ == type_:
                feature_list.append(feature)

        return feature_list

    def get_base_color(self):
        # Give the map a base color
        base_rgb_color = g.MCFG[self.region]['base_color']
        if base_rgb_color == 'use_world_map':
            base_color = self.color
        else:
            base_color = libtcod.Color(*base_rgb_color)

        return base_color

    def add_minor_site(self, site):
        ''' Takes an already created site and adds it to the map '''
        self.minor_sites.append(site)
        self.all_sites.append(site)

        g.WORLD.all_sites.append(site)

        # CHUNK
        self.chunk.add_minor_site(site)

    def create_and_add_minor_site(self, world, type_, char, name, color):
        ''' Creates a new instance of a Site and adds it to the map '''
        site = Site(world, type_, self.x, self.y, char, name, color)
        self.add_minor_site(site)

        return site

    def add_cave(self, world, name):
        cave = Site(world=world, type_='cave', x=self.x, y=self.y, char=g.CAVE_CHAR, name=name, color=libtcod.black, underground=1)
        self.caves.append(cave)
        self.all_sites.append(cave)
        self.char = g.CAVE_CHAR

        g.WORLD.all_sites.append(cave)

        # CHUNK
        self.chunk.add_cave(cave)


    def get_location_description(self):
        if self.site:
            return self.site.name
        # Say the name of the site, unless it is being described relative to other cities
        elif len(self.minor_sites) or len(self.caves):
            site_names = [site.get_name() for site in self.minor_sites + self.caves]
            return join_list(site_names)
        else:
            city, dist = g.WORLD.get_closest_city(self.x, self.y)
            if dist == 0:
                return '{0}'.format(city.name)
            elif 0 < dist <= 3:
                return 'the {0} just to the {1} of {2}'.format(pl(self.region), cart2card(city.x, city.y, self.x, self.y), city.name)
            elif dist <= 15:
                return 'the {0} to the {1} of {2}'.format(pl(self.region), cart2card(city.x, city.y, self.x, self.y), city.name)
            elif dist > 75:
                return 'the distant {0}ern {1}'.format(cart2card(city.x, city.y, self.x, self.y), pl(self.region))
            elif dist > 50:
                return 'the {0} far, far to the {1} of {2}'.format(pl(self.region), cart2card(city.x, city.y, self.x, self.y), city.name)
            elif dist > 15:
                return 'the {0} far to the {1} of {2}'.format(pl(self.region), cart2card(city.x, city.y, self.x, self.y), city.name)
            else:
                return 'the unknown {0}'.format(pl(self.region))

    def get_location_description_relative_to(self, relative_location):

        wx, wy = relative_location
        dist = g.WORLD.get_astar_distance_to(self.x, self.y, wx, wy)

        if self.x == wx and self.y == wy:
            return 'this very place'
        elif dist is None:
            return 'the unreachable {0}'.format(pl(self.region))
        elif dist < 30:
            return 'the {0} about {1} days\' journey to the {2}'.format(pl(self.region), dist, cart2card(wx, wy, self.x, self.y))
        else:
            return 'the {0} far to the {1}'.format(pl(self.region), cart2card(wx, wy, self.x, self.y))




class World(Map):
    def __init__(self, width, height):
        Map.__init__(self, width, height)


        self.time_cycle = TimeCycle(self)

        self.sites = []
        self.all_sites = []
        self.resources = []
        self.ideal_locs = []

        self.dynasties = []
        self.all_figures = []
        self.important_figures = []

        self.famous_objects = set([])
        ### TODO - move this around; have it use the actual language of the first city
        self.moons, self.suns = religion.create_astronomy()

        self.equator = None
        self.mountains = []
        self.rivers = []

        # Contiguous region set for play:
        self.play_region  = None
        # Tuple of all play tiles
        self.play_tiles = None

        # Set up other important lists
        self.default_mythic_culture = None
        self.sentient_races = []
        self.brutish_races = []

        self.cultures = []
        self.languages = []
        self.ancient_languages = []
        self.lingua_franca = None

        self.cities = []
        self.hideouts = []
        self.factions = []

        self.site_index = defaultdict(list)

        # Dijmap where cities are the root nodes; set after cities are generated
        self.distance_from_civilization_dmap = None


        self.tiles_with_potential_encounters = set([])

        ## Set on initialize_fov() call
        self.fov_recompute = False
        self.fov_map = None
        self.path_map = None
        self.rook_path_map = None
        self.road_fov_map = None
        self.road_path_map = None

        # economy.setup_resources()
        #### load phys info ####
        phys.main()

        # Out of order for now, to get creation myth on load screen
        self.generate_mythological_creatures()
        self.cm = religion.CreationMyth(creator=self.default_mythic_culture.pantheon.gods[0], pantheon=self.default_mythic_culture.pantheon)
        self.cm.create_myth()
        #self.generate()

    def add_famous_object(self, obj):
        self.famous_objects.add(obj)

    def remove_famous_object(self, obj):
        self.famous_objects.remove(obj)

    def add_to_site_index(self, site):
        self.site_index[site.type_].append(site)

    def generate(self):
        #### Setup actual world ####
        steps = 6
        g.game.render_handler.progressbar_screen('Generating World Map', 'creating regions', 1, steps, [] ) # self.cm.story_text)
        self.setup_world()
        ########################### Begin with heightmap ##################################
        g.game.render_handler.progressbar_screen('Generating World Map', 'generating heightmap', 2, steps, []) # self.cm.story_text)
        self.make_heightmap()
        ## Now, loop through map and check each land tile for its distance to water
        g.game.render_handler.progressbar_screen('Generating World Map', 'setting moisture', 3, steps, []) # self.cm.story_text)
        self.calculate_water_dist()

        ##### EXPERIMENTOIAENH ######
        #self.calculate_rainfall()
        ########################## Now, generate rivers ########################
        g.game.render_handler.progressbar_screen('Generating World Map', 'generating rivers', 4, steps, []) # self.cm.story_text)
        self.generate_rivers()
        ################################ Resources ##########################################
        g.game.render_handler.progressbar_screen('Generating World Map', 'setting resources and biome info', 5, steps, []) #self.cm.story_text)

        # Print out creation myth
        #for line in self.cm.story_text:
        #    g.game.add_message(line)

        self.set_resource_and_biome_info()

        ##### End setup actual world #####

        # For pathing
        self.divide_into_regions()

        ######## Add some buttons #######
        panel2.wmap_buttons = [
                          gui.Button(gui_panel=panel2, func=self.generate_history, args=[1],
                                     text='Generate History', topleft=(4, g.PANEL2_HEIGHT-11), width=20, height=5, color=g.PANEL_FRONT, do_draw_box=True),
                          gui.Button(gui_panel=panel2, func=self.generate, args=[],
                                     text='Regenerate Map', topleft=(4, g.PANEL2_HEIGHT-6), width=20, height=5, color=g.PANEL_FRONT, do_draw_box=True)
                          ]

    def tile_blocks_mov(self, x, y):
        if self.tiles[x][y].blocks_mov:
            return True

    def draw_world_objects(self):
        # Just have all world objects represent themselves
        for figure in g.WORLD.all_figures:
            if not self.tiles[figure.wx][figure.wy].site:
                figure.w_draw()

        for site in self.sites:
            site.w_draw()

        if g.player is not None:
            g.player.w_draw()

    #####################################

    def make_world_road(self, x, y):
        ''' Add a road to the tile's features '''
        if not self.tiles[x][y].has_feature('road'):
            self.tiles[x][y].features.append(Feature(type_='road', x=x, y=y))

    def set_road_tile(self, x, y):
        N, S, E, W = 0, 0, 0, 0
        if self.tiles[x+1][y].has_feature('road'):
            E = 1
        if self.tiles[x-1][y].has_feature('road'):
            W = 1
        if self.tiles[x][y+1].has_feature('road'):
            S = 1
        if self.tiles[x][y-1].has_feature('road'):
            N = 1

        char = self.get_line_tile_based_on_surrounding_tiles(N, S, E, W)
        if char is None:
            return

        self.tiles[x][y].char = char
        self.tiles[x][y].char_color = libtcod.darkest_sepia


    def get_line_tile_based_on_surrounding_tiles(self, N, S, E, W):
        ''' Determines a tile for a river or road based on the connections it has '''
        if N and S and E and W:     char = 648 # chr(197)
        elif N and S and E:         char = 644 # chr(195)
        elif N and E and W:         char = 640 # chr(193)
        elif S and E and W:         char = 642 # chr(194)
        elif N and S and W:         char = 614 # chr(180)
        elif E and W:               char = 646 # chr(196)
        elif E and N:               char = 638 # chr(192)
        elif N and S:               char = 612 # chr(179)
        elif N and W:               char = 688 # chr(217)
        elif S and W:               char = 636 # chr(191)
        elif S and E:               char = 690 # chr(218)
        elif N:                     char = 612 # chr(179)
        elif S:                     char = 612 # chr(179)
        elif E:                     char = 646 # chr(196)
        elif W:                     char = 646 # chr(196)
        elif not (N and S and E and W):
            char = 255 # Empty character

        return char

    def get_surrounding_tile_heights(self, coords):
        ''' Return a list of the tile heights surrounding this one, including this tile itself '''
        x, y = coords

        heights = []

        for xx in xrange(x-1, x+2):
            for yy in xrange(y-1, y+2):
                if self.is_val_xy((xx, yy)):
                    heights.append(self.tiles[xx][yy].height)

                # If map edge, just append this tile's own height
                else:
                    heights.append(self.tiles[x][y].height)

        return heights


    def get_surrounding_heights(self, coords):
        world_x, world_y = coords
        surrounding_heights = []
        for x in xrange(world_x-1, world_x+2):
            for y in xrange(world_y-1, world_y+2):
                surrounding_heights.append(self.tiles[x][y].height)

        return surrounding_heights

    def get_surrounding_rivers(self, coords):
        ''' Return a list of the tile heights surrounding this one, including this tile itself '''
        x, y = coords

        river_dirs = []

        for xx, yy in get_border_tiles(x, y):
            if self.is_val_xy((xx, yy)) and self.tiles[xx][yy].has_feature('river'):
                river_dirs.append((x-xx, y-yy))

        ## Quick hack for now - append oceans to rivers
        if len(river_dirs) == 1:
            for xx, yy in get_border_tiles(x, y):
                if self.is_val_xy((xx, yy)) and self.tiles[xx][yy].region == 'ocean':
                    river_dirs.append((x-xx, y-yy))
                    break

        return river_dirs

    def get_closest_city(self, x, y, max_range=1000, valid_cities='all_cities_in_world'):
        ''' Find closest city from a given location. Optionally pass in a list of cities to restrict search by '''
        cities = self.cities if valid_cities == 'all_cities_in_world' else valid_cities

        # Attepmt to shave some time from the expensive astar algo below by checking if the current tile is a valid city,
        # and cut the function short by returning that site if so
        if self.tiles[x][y].site and self.tiles[x][y].site in cities:
            return self.tiles[x][y].site, 0

        # Normal case - loop through all cities and track distance / closest distance until we find the minimum
        closest_city = None
        closest_dist = max_range + 1  #start with (slightly more than) maximum range

        for city in cities:
            dist = self.get_astar_distance_to(x, y, city.x, city.y)
            if  dist < closest_dist: #it's closer, so remember it
                closest_city = city
                closest_dist = dist
        return closest_city, closest_dist

    def find_nearby_resources(self, x, y, distance):
        # TODO - this code is pretty gnarly :-/
        # Make a list of nearby resources at particular world coords
        nearby_resources = []
        nearby_resource_locations = []
        for wx in xrange(x - distance, x + distance + 1):
            for wy in xrange(y - distance, y + distance + 1):
                if self.is_val_xy( (wx, wy) ) and self.tiles[wx][wy].res:
                    # Make sure there's a path to get the resource from (not blocked by ocean or whatever)
                    path = libtcod.path_compute(self.rook_path_map, x, y, wx, wy)
                    new_path_len = libtcod.path_size(self.rook_path_map)

                    if new_path_len:
                        for resource in self.tiles[wx][wy].res.iterkeys():
                            ## Only add it if it's not already in it, and if we don't have access to it
                            if not resource in nearby_resources: # and not resource in self.native_res.keys():
                                nearby_resources.append(resource)
                                nearby_resource_locations.append((wx, wy))

                            elif resource in nearby_resources:
                                ## Check whether the current instance of this resource is closer than the previous one
                                cur_dist = self.get_astar_distance_to(x, y, wx, wy)

                                prev_res_ind = nearby_resources.index(resource)
                                px, py = nearby_resource_locations[prev_res_ind]
                                prev_dist = self.get_astar_distance_to(x, y, px, py)

                                if cur_dist < prev_dist:
                                    del nearby_resources[prev_res_ind]
                                    del nearby_resource_locations[prev_res_ind]

                                    nearby_resources.append(resource)
                                    nearby_resource_locations.append((wx, wy))

        return nearby_resources, nearby_resource_locations

    def get_closest_resource(self, x, y, resource):
        ''' Given world x and y coords, find the closest instance of a particular resource '''
        initial_chunk = self.tiles[x][y].chunk
        resource_locations = [location for location in initial_chunk.resources[resource] if resource in initial_chunk.resources]
        # Check if there are any on this chunk
        closest_distance, closest_location = self.get_closest_location(x=x, y=y, locations=resource_locations)

        # If there is a distance, and it's less than the chunk size, then this is a good location
        if 0 <= closest_distance <= self.chunk_size:
            return closest_distance, closest_location

        # Find a list of nearby chunks to check the resources of - arbitrarily setting # of chunks to 5 for now
        resource_locations = [location for chunk in self.get_nearby_chunks(chunk=initial_chunk, distance=3)
                                       if chunk != initial_chunk for location in chunk.resources[resource]
                                       if resource in chunk.resources and self.tiles[location[0]][location[1]].in_play_region()]

        closest_distance, closest_location = self.get_closest_location(x=x, y=y, locations=resource_locations)

        return closest_distance, closest_location

    def get_random_location_away_from_civilization(self, min_dist, max_dist):
        ''' Finds a random tile in the play area that is within a range of distances from civilization '''
        assert min_dist <= max_dist

        # Loop through the play tiles until a tile is found that meets the criteria
        while True:
            wx, wy = random.choice(self.play_tiles)

            if min_dist <= self.distance_from_civilization_dmap.dmap[wx][wy] <= max_dist:
                break

        return (wx, wy)


    def setup_world(self):
        # Fill world with empty regions
        self.tiles = [[Region(x=x, y=y) for y in xrange(self.height)] for x in xrange(self.width)]
        # Initialize the chunks inthe world - method inherited from map_base
        self.setup_chunks(chunk_size=10, map_type='world')

        # Equator line - temperature depends on this. Varies slightly from map to map
        self.equator = int(round(self.height / 2)) + roll(-5, 5)

    def distance_to_equator(self, y):
        return abs(y - self.equator) / (self.height / 2)


    def make_heightmap(self):
        hm = libtcod.heightmap_new(self.width, self.height)
        # Start with a bunch of small, wide hills. Keep them relatively low
        for iteration in xrange(200):
            maxrad = roll(10, 50)

            x, y = roll(maxrad, self.width - maxrad), roll(maxrad, self.height - maxrad)
            if libtcod.heightmap_get_value(hm, x, y) < 80:
                libtcod.heightmap_add_hill(hm, x, y, roll(1, maxrad), roll(10, 25))
            if roll(1, 4) == 1:
                libtcod.heightmap_dig_hill(hm, x, y, roll(4, 20), roll(10, 30))

        # Then add mountain ranges. Should be tall and thin
        for iteration in xrange(100):
            maxrad = 5
            maxlen = 20 + maxrad
            minheight = 5
            maxheight = 10

            x = roll(maxlen, self.width - maxlen)
            y = roll(int(round(self.height / 10)), self.height - int(round(self.height / 10)))

            if libtcod.heightmap_get_value(hm, x, y) < 120:
                libtcod.line_init(x, y, roll(x - maxlen, x + maxlen), roll(y - maxlen, y + maxlen))
                nx, ny = x, y

                while nx is not None:
                    if libtcod.heightmap_get_value(hm, x, y) < 140:
                        libtcod.heightmap_add_hill(hm, nx, ny, roll(1, maxrad), roll(minheight, maxheight))
                    nx, ny = libtcod.line_step()


        ## Added 4/28/2014 - World size must be a power of 2 plus 1 for this to work
        #libtcod.heightmap_mid_point_displacement(hm=hm, rng=0, roughness=.5)

        # Erosion - not sure exactly what these params do
        libtcod.heightmap_rain_erosion(hm=hm, nbDrops=self.width * self.height, erosionCoef=.05, sedimentationCoef=.05, rnd=0)

        # And normalize heightmap
        #libtcod.heightmap_normalize(hm, mi=1, ma=255)
        libtcod.heightmap_normalize(hm, mi=1, ma=220)
        #libtcod.heightmap_normalize(hm, mi=20, ma=170)

        ### Noise to vary wdist ### Experimental code ####
        mnoise = libtcod.noise_new(2, libtcod.NOISE_DEFAULT_HURST, libtcod.NOISE_DEFAULT_LACUNARITY)
        octaves = 20
        div_amt = 20

        thresh = .4
        thresh2 = .8
        scale = 130
        mvar = 30
        ### End experimental code ####


        # Add the info from libtcod's heightmap to the world's heightmap
        for x in xrange(self.width):
            for y in xrange(self.height):
                ############# New ####################
                val = libtcod.noise_get_turbulence(mnoise, [x / div_amt, y / div_amt], octaves, libtcod.NOISE_SIMPLEX)
                #### For turb map, low vals are "peaks" for us ##############
                if val < thresh and self.height / 10 < y < self.height - (self.height / 10):
                    raise_terr = int(round(scale * (1 - val))) + roll(-mvar, mvar)
                elif val < thresh2:
                    raise_terr = int(round((scale / 2) * (1 - val))) + roll(-int(round(mvar / 2)), int(round(mvar / 2)))
                else:
                    raise_terr = 0

                self.tiles[x][y].height = int(round(libtcod.heightmap_get_value(hm, x, y))) + raise_terr
                self.tiles[x][y].height = min(self.tiles[x][y].height, 255)

                if not 5 < x < self.width - 5 and self.tiles[x][y].height >= g.WATER_HEIGHT:
                    self.tiles[x][y].height = 99
                    #######################################
                if self.tiles[x][y].height > 200:
                    self.mountains.append((x, y))

                #### While we're looping, we might as well add temperature information
                # weird formula for approximating temperature based on height and distance to equator

                ''' Original settings '''
                base_temp = 16
                height_mod = ((1.05 - (self.tiles[x][y].height / 255)) * 4)
                equator_mod = (1.3 - self.distance_to_equator(y)) ** 2

                ''' Newer expermiental settings '''
                #base_temp = 40
                #height_mod = 1
                #equator_mod = (1.3 - self.distance_to_equator(y)) ** 2

                self.tiles[x][y].temp = base_temp * height_mod * equator_mod

                #### And start seeding the water distance calculator
                if self.tiles[x][y].height < g.WATER_HEIGHT:
                    self.tiles[x][y].wdist = 0
                    self.tiles[x][y].moist = 0
                else:
                    self.tiles[x][y].wdist = None
                    self.tiles[x][y].moist = 100

        # Finally, delete the libtcod heightmap from memory
        libtcod.heightmap_delete(hm)


    '''
    def calculate_rainfall(self):
        # An ok way to calclate rainfall?

        for y in xrange(self.height):
            # Seed initial rainfall based on lattitude
            if 30 < y < self.height-30 or 20 < abs(y-self.equator):
                rainfall = -10
            else:
                rainfall = 10

            # West -> east winds
            for x in xrange(self.width):
                self.tiles[x][y].rainfall = rainfall

                if self.tiles[x][y].height <= g.WATER_HEIGHT:
                    rainfall += 1
                elif self.tiles[x][y].height <= g.MOUNTAIN_HEIGHT:
                    rainfall -= 1
                else:
                    rainfall = 0

            # East -> west winds
            #for x in xrange(self.width):
            #    self.tiles[self.width-x][y].rainfall = rainfall
            #
            #    if self.tiles[self.width-x][y].height <= g.WATER_HEIGHT:
            #        rainfall += 1
            #    elif self.tiles[self.width-x][y].height <= g.MOUNTAIN_HEIGHT:
            #        rainfall -= 1
            #    else:
            #        rainfall = 0
    '''

    def calculate_water_dist(self):
        ## Essentially a dijisktra map for water distance
        wdist = 0
        found_square = True
        while found_square:
            found_square = False
            wdist += 1

            for x in xrange(1, self.width - 1):
                for y in xrange(1, self.height - 1):

                    if self.tiles[x][y].wdist is None:
                        # Only check water distance at 4 cardinal directions
                        #side_dir = [(x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)]
                        #corner_dir = [(x-1, y-1), (x-1, y+1), (x+1, y-1), (x+1, y+1)]
                        for dx, dy in get_border_tiles(x, y):
                            if self.tiles[dx][dy].wdist == wdist - 1:
                                self.tiles[x][y].wdist = self.tiles[dx][dy].wdist + 1
                                # calculate "moisture" to add a little variability - it's related to water dist but takes height into account
                                # Also, LOWER is MORE moist because I'm lazy
                                self.tiles[x][y].moist = self.tiles[x][y].wdist * (1.7 - (self.tiles[x][y].height / 255)) ** 2

                                found_square = True
                                break

    def generate_rivers(self):
        self.rivers = []
        river_connection_tiles = []
        # Walk through all mountains tiles and make a river if there are none nearby
        while len(self.mountains) > 1:
            # Pop out a random mountain tile
            (x, y) = self.mountains.pop(roll(0, len(self.mountains) - 1) )
            # Check if another river already exists nearby, and abort if so
            make_river = True
            for riv_x in xrange(x - 4, x + 5):
                for riv_y in xrange(y - 4, y + 5):
                    if self.tiles[riv_x][riv_y].has_feature('river'):
                        make_river = False
                        break

            if make_river:
                # create a river
                #self.tiles[x][y].features.append(River(x=x, y=y))
                riv_cur = [(x, y)]

                new_x, new_y = x, y
                found_lower_height = True
                i = 0
                while self.tiles[new_x][new_y].height > g.WATER_HEIGHT:
                    i += 1
                    if i >= 100:
                        logging.debug('river loop exceeded 100 iterations')
                        break

                    cur_x, cur_y = new_x, new_y

                    # Rivers try to flow through lower areas
                    low_height = self.tiles[new_x][new_y].height
                    if found_lower_height:
                        found_lower_height = False
                        for rx, ry in get_border_tiles(new_x, new_y):
                            if self.tiles[rx][ry].height <= low_height: # and not (nx, ny) in riv_cur:
                                low_height = self.tiles[rx][ry].height
                                new_x, new_y = rx, ry
                                found_lower_height = True

                    # if it does get trapped in a local minimum, flow in the direction of the lowest distance to water
                    # and preferentially in the lowest height of these tiles
                    if not found_lower_height:
                        wdist = 1000
                        height = 1000

                        for nx, ny in get_border_tiles(new_x, new_y):
                            if self.tiles[nx][ny].wdist <= wdist and self.tiles[nx][ny].height < height and not (nx, ny) in riv_cur:
                                wdist = self.tiles[nx][ny].wdist
                                height = self.tiles[nx][ny].height
                                new_x, new_y = nx, ny

                    if self.tiles[new_x][new_y].height < g.WATER_HEIGHT:
                        break

                    if not self.tiles[new_x][new_y].has_feature('river'):
                        riv_cur.append((new_x, new_y))
                        ### Rivers cut through terrain if needed, and also make the areas around them more moist
                        # Try to lower the tile's height if it's higher than the previous tile, but don't go lower than 100
                        self.tiles[new_x][new_y].height = min(self.tiles[new_x][new_y].height, max(self.tiles[cur_x][cur_y].height - 1, g.WATER_HEIGHT))
                        for rx, ry in get_border_tiles(new_x, new_y):
                            self.tiles[rx][ry].moist /= 2

                    # If a river exists on the new tiles, stop
                    else:
                        river_connection_tiles.append((new_x, new_y))
                        break

                # This sets the tile and color of the river
                for i, (x, y) in enumerate(riv_cur):
                    self.tiles[x][y].char_color = libtcod.Color(20, 45, int(round(self.tiles[x][y].height)))
                    river_feature = River(x=x, y=y)
                    self.tiles[x][y].features.append(river_feature)

                    N, S, E, W = 0, 0, 0, 0

                    #### If this is not the first tile of the river...
                    if i > 0:
                        px, py = riv_cur[i - 1]
                        if i < len(riv_cur) - 1:
                            nx, ny = riv_cur[i + 1]

                        d1x, d1y = px - x, py - y
                        if (d1x, d1y) == (-1, 0) or self.tiles[x - 1][y].height < g.WATER_HEIGHT: W = 1
                        if (d1x, d1y) == (1, 0) or self.tiles[x + 1][y].height < g.WATER_HEIGHT: E = 1
                        if (d1x, d1y) == (0, 1) or self.tiles[x][y + 1].height < g.WATER_HEIGHT: S = 1
                        if (d1x, d1y) == (0, -1) or self.tiles[x][y - 1].height < g.WATER_HEIGHT: N = 1

                        river_feature.add_connected_dir(direction=(d1x, d1y))

                        if i < len(riv_cur) - 1:
                            d2x, d2y = nx - x, ny - y
                            if (d2x, d2y) == (-1, 0) or self.tiles[x - 1][y].height < g.WATER_HEIGHT: W = 1
                            if (d2x, d2y) == (1, 0) or self.tiles[x + 1][y].height < g.WATER_HEIGHT: E = 1
                            if (d2x, d2y) == (0, 1) or self.tiles[x][y + 1].height < g.WATER_HEIGHT: S = 1
                            if (d2x, d2y) == (0, -1) or self.tiles[x][y - 1].height < g.WATER_HEIGHT: N = 1

                            river_feature.add_connected_dir(direction=(d2x, d2y))

                    #### If this is the first tile of the river...
                    elif i == 0:
                        if (x - 1, y) in riv_cur:   W = 1
                        elif (x + 1, y) in riv_cur: E = 1
                        elif (x, y + 1) in riv_cur: S = 1
                        elif (x, y - 1) in riv_cur: N = 1

                    char = self.get_line_tile_based_on_surrounding_tiles(N, S, E, W)
                    self.tiles[x][y].char = char

                self.rivers.append(riv_cur)

        # Add special tiles where rivers intersect
        ## TODO - does not work as intended in all cases (considering all nearby tiles when it should only consider ones it has directly connected to)
        for x, y in river_connection_tiles:
            N, S, E, W = 0, 0, 0, 0
            if self.tiles[x-1][y].has_feature('river'): W = 1
            if self.tiles[x+1][y].has_feature('river'): E = 1
            if self.tiles[x][y+1].has_feature('river'): S = 1
            if self.tiles[x][y-1].has_feature('river'): N = 1

            char = self.get_line_tile_based_on_surrounding_tiles(N, S, E, W)
            self.tiles[x][y].char = char

        ## Experimental code to vary moisture and temperature a bit
        noisemap1 = libtcod.noise_new(2, libtcod.NOISE_DEFAULT_HURST, libtcod.NOISE_DEFAULT_LACUNARITY)
        noisemap2 = libtcod.noise_new(2, libtcod.NOISE_DEFAULT_HURST, libtcod.NOISE_DEFAULT_LACUNARITY)

        n1octaves = 12
        n2octaves = 10

        n1div_amt = 75
        n2div_amt = 50

        n1scale = 20
        n2scale = 15
        #1576
        ## Map edge is unwalkable
        for y in xrange(self.height):
            for x in xrange(self.width):
                # moist
                w_val = libtcod.noise_get_fbm(noisemap1, [x / n1div_amt, y / n1div_amt], n1octaves, libtcod.NOISE_SIMPLEX)
                w_val += .1
                self.tiles[x][y].moist =  max(0, self.tiles[x][y].moist + int(round(w_val * n1scale)) )
                # temp
                t_val = libtcod.noise_get_fbm(noisemap2, [x / n2div_amt, y / n2div_amt], n2octaves, libtcod.NOISE_SIMPLEX)
                self.tiles[x][y].temp += int(round(t_val * n2scale))
        ### End experimental code ####


    def set_resource_and_biome_info(self):
        ''' TODO NEW FUNCTION DEFINITION TO MODIFY FOR NEW RAIN CODE '''
        ''' Finally, use the scant climate info generated to add biome and color information '''

        mountain_height = g.MOUNTAIN_HEIGHT # minor optimization to make variable local
        water_height = g.WATER_HEIGHT # minor optimization to make variable local

        taiga_chars = (chr(5), '^')
        forest_chars = (chr(5), chr(6))
        rain_forest_chars = (chr(6), '*')

        # Hardcoded positions where tundra cannot go in between (e.g. none in between world y height of tundra_min and tundra_max)
        tundra_min = 35
        tundra_max = self.height - 35
        # Hardcoded positions where tundra cannot go in between (e.g. none in between world y height of tundra_min and tundra_max)
        taiga_min = 45
        taiga_max = self.height - 45

        a = 3 # Used for coloring tiles (each rgb value will vary by +- this #)

        for y in xrange(self.height):
            for x in xrange(self.width):
                this_tile = self.tiles[x][y] # minor optimization to avoid lookups

                sc = int(this_tile.height) - 1
                mmod = int(round(40 - this_tile.moist) / 1.4) - 25

                ## Ocean
                if this_tile.height < water_height:
                    this_tile.blocks_mov = True
                    this_tile.region = 'ocean'

                    this_tile.clear_all_resources()

                    if this_tile.height < 75:
                        this_tile.color = libtcod.Color(7, 13, int(round(sc * 2)) + 10)
                    else:
                        this_tile.color = libtcod.Color(20, 60, int(round(sc * 2)) + 15)

                #### MOUNTAIN ####
                elif this_tile.height > mountain_height:
                    this_tile.blocks_mov = True
                    this_tile.blocks_vis = True
                    this_tile.region = 'mountain'

                    this_tile.clear_all_resources()

                    c = int(round((this_tile.height - 200) / 2))
                    d = -int(round(c / 2))
                    this_tile.color = libtcod.Color(d + 43 + roll(-a, a), d + 55 + roll(-a, a), d + 34 + roll(-a, a))
                    if this_tile.height > 235:      this_tile.char_color = libtcod.grey # Tall mountain - snowy peak
                    else:                           this_tile.char_color = libtcod.Color(c + 38 + roll(-a, a), c + 25 + roll(-a, a), c + 21 + roll(-a, a))
                    this_tile.char = g.MOUNTAIN_TILE

                ######################## TUNDRA ########################
                elif this_tile.temp < 18 and not (tundra_min < y < tundra_max):
                    this_tile.region = 'tundra'
                    this_tile.color = libtcod.Color(190 + roll(-a - 2, a + 2), 188 + roll(-a - 2, a + 2), 189 + roll(-a - 2, a + 2))

                ######################## TAIGA ########################
                elif this_tile.temp < 23 and this_tile.moist < 22 and not (taiga_min < y < taiga_max):
                    this_tile.region = 'taiga'
                    this_tile.color = libtcod.Color(127 + roll(-a, a), 116 + roll(-a, a), 115 + roll(-a, a))

                    if not this_tile.has_feature('river'):
                        this_tile.char_color = libtcod.Color(23 + roll(-a, a), 58 + mmod + roll(-a, a), 9 + roll(-a, a))
                        this_tile.char = random.choice(g.TAIGA_TILES)

                ######################## TEMPERATE FOREST ########################
                elif this_tile.temp < 30 and this_tile.moist < 18:
                    this_tile.region = 'temperate forest'
                    this_tile.color = libtcod.Color(53 + roll(-a, a), 75 + mmod + roll(-a, a), 32 + roll(-a, a))

                    if not this_tile.has_feature('river'):
                        this_tile.char_color = libtcod.Color(25 + roll(-a, a), 55 + mmod + roll(-a, a), 20 + roll(-a, a))
                        this_tile.char = random.choice(g.FOREST_TILES)

                ######################## TEMPERATE STEPPE ########################
                elif this_tile.temp < 35:
                    this_tile.region = 'temperate steppe'
                    this_tile.color = libtcod.Color(65 + roll(-a, a), 97 + mmod + roll(-a, a), 41 + roll(-a, a))

                    if not this_tile.has_feature('river'):
                        this_tile.char_color = this_tile.color * .85
                        this_tile.char = g.TEMPERATE_STEPPE_TILE

                ######################## RAIN FOREST ########################
                elif this_tile.temp > 47 and this_tile.moist < 18:
                    this_tile.region = 'rain forest'
                    this_tile.color = libtcod.Color(40 + roll(-a, a), 60 + mmod + roll(-a, a), 18 + roll(-a, a))

                    if not this_tile.has_feature('river'):
                        this_tile.char_color = libtcod.Color(16 + roll(-a, a), 40 + roll(-a - 5, a + 5), 5 + roll(-a, a))
                        this_tile.char = random.choice(g.RAIN_FOREST_TILES)

                ######################## TREE SAVANNA ########################
                elif this_tile.temp >= 35 and this_tile.moist < 18:
                    this_tile.region = 'tree savanna'
                    this_tile.color = libtcod.Color(50 + roll(-a, a), 85 + mmod + roll(-a, a), 25 + roll(-a, a))
                    #this_tile.color = libtcod.Color(209, 189, 126)  # grabbed from a savannah image
                    #this_tile.color = libtcod.Color(139, 119, 56)

                    if not this_tile.has_feature('river'):
                        if roll(1, 5) > 1:
                            this_tile.char_color = this_tile.color * .85
                            this_tile.char = g.TEMPERATE_STEPPE_TILE
                        else:
                            this_tile.char_color = this_tile.color * .75
                            this_tile.char = g.TREE_SAVANNA_TILE

                ######################## GRASS SAVANNA ########################
                elif this_tile.temp >= 35 and this_tile.moist < 34:
                    this_tile.region = 'grass savanna'
                    this_tile.color = libtcod.Color(91 + roll(-a, a), 110 + mmod + roll(-a, a), 51 + roll(-a, a))
                    #this_tile.color = libtcod.Color(209, 189, 126) # grabbed from a savannah image
                    #this_tile.color = libtcod.Color(179, 169, 96)

                    if not this_tile.has_feature('river'):
                        this_tile.char_color = this_tile.color * .80
                        this_tile.char = g.TEMPERATE_STEPPE_TILE

                ######################## DRY STEPPE ########################
                elif this_tile.temp <= 44:
                    this_tile.region = 'dry steppe'
                    this_tile.color = libtcod.Color(99 + roll(-a, a), 90 + roll(-a, a + 1), 59 + roll(-a, a + 1))

                ######################## SEMI-ARID DESERT ########################
                elif this_tile.temp > 44 and this_tile.moist < 48:
                    this_tile.region = 'semi-arid desert'
                    this_tile.color = libtcod.Color(178 + roll(-a - 1, a + 2), 140 + roll(-a - 1, a + 2), 101 + roll(-a - 1, a + 2))

                ######################## ARID DESERT ########################
                elif this_tile.temp > 44:
                    this_tile.region = 'arid desert'
                    this_tile.color = libtcod.Color(212 + roll(-a - 1, a + 1), 185 + roll(-a - 1, a + 1), 142 + roll(-a - 1, a + 1))

                # Hopefully shouldn't come to this
                else:
                    this_tile.region = 'none'
                    this_tile.color = libtcod.red


                #### New code - add resources
                for resource in data.commodity_manager.resources:
                    for biome, chance in resource.app_chances.iteritems():
                        if biome == this_tile.region or (biome == 'river' and this_tile.has_feature('river')):
                            if roll(1, 1200) < chance:
                                this_tile.add_resource(resource.name, resource.app_amt)

                                # Hack in the ideal locs and start locs
                                if resource.name == 'food':
                                    self.ideal_locs.append((x, y))

        # Need to calculate pathfinding
        self.initialize_fov()

        ## Try to shade the map
        max_alpha = .9
        hill_excluders = {'mountain', 'temperate forest', 'rain forest'}

        for y in xrange(2, self.height-2):
            for x in xrange(2, self.width-2):
                this_tile = self.tiles[x][y]
                if this_tile.region != 'ocean' and self.tiles[x+1][y].region != 'ocean':
                    hdif = this_tile.height / self.tiles[x+1][y].height

                    if hdif <= 1:
                        alpha = max(hdif, max_alpha)
                        this_tile.color = libtcod.color_lerp(libtcod.lightest_sepia, this_tile.color, alpha )
                        if not this_tile.has_feature('river'):
                            this_tile.char_color = libtcod.color_lerp(libtcod.white, this_tile.char_color, alpha )
                    elif hdif > 1:
                        alpha = max(2 - hdif, max_alpha)
                        this_tile.color = libtcod.color_lerp(libtcod.darkest_sepia, this_tile.color, alpha)
                        if not this_tile.has_feature('river'):
                            this_tile.char_color = libtcod.color_lerp(libtcod.darkest_sepia, this_tile.char_color, alpha)

                    # Experimental badly placed code to add a "hill" character to hilly map spots
                    if alpha == max_alpha and not(this_tile.region in hill_excluders) and not this_tile.has_feature('river'):
                        this_tile.char = g.HILL_TILE
                        # if this_tile.region in ('semi-arid desert', 'arid desert', 'dry steppe'):
                        this_tile.char_color = this_tile.color - libtcod.Color(20, 20, 20)

                ################## OUT OF PLACE CAVE GEN CODE ###############
                if this_tile.region != 'mountain' and this_tile.height > mountain_height-10 and roll(1, 100) <= 20:
                    this_tile.add_cave(world=self, name=None)


        exclude_smooth = {'ocean'}
        # Smooth the colors of the world
        for y in xrange(2, self.height - 2):
            for x in xrange(2, self.width - 2):
                if not self.tiles[x][y].region in exclude_smooth:
                    neighbors = ((x - 1, y - 1), (x - 1, y), (x, y - 1), (x + 1, y), (x, y + 1), (x + 1, y + 1), (x + 1, y - 1), (x - 1, y + 1))
                    #colors = [g.WORLD.tiles[nx][ny].color for (nx, ny) in neighbors]
                    if not self.tiles[x][y].region == 'mountain':
                        smooth_coef = .25
                    else:
                        smooth_coef = .1

                    #border_ocean = 0
                    used_regions = {'ocean'} #Ensures color_lerp doesn't try to interpolate with almost all of the neighbors
                    for nx, ny in neighbors:
                        if self.tiles[nx][ny].region != self.tiles[x][y].region and self.tiles[nx][ny].region not in used_regions:
                            used_regions.add(self.tiles[ny][ny].region)
                            self.tiles[x][y].color = libtcod.color_lerp(self.tiles[x][y].color, self.tiles[nx][ny].color, smooth_coef)
                        #if self.tiles[nx][ny].region == 'ocean':
                        #    border_ocean = 1
                    ## Give a little bit of definition to coast tiles
                    #if border_ocean:
                    #    self.tiles[x][y].color = libtcod.color_lerp(self.tiles[x][y].color, libtcod.Color(212, 185, 142), .1)

                '''
				# Smooth oceans too
				else:
					smooth_coef = .1
					neighbors = [(x-1, y-1), (x-1, y), (x, y-1), (x+1, y), (x, y+1), (x+1, y+1), (x+1, y-1), (x-1,y+1)]
					for nx, ny in neighbors:
						if self.tiles[nx][ny].region == self.tiles[x][y].region:
							self.tiles[x][y].color = libtcod.color_lerp(self.tiles[x][y].color, self.tiles[nx][ny].color, smooth_coef)
				'''

    def divide_into_regions(self):
        ''' Divides the world into regions, and chooses the biggest one (continent) to start civilization on '''
        current_region_number = 0

        biggest_region_size = 0
        biggest_region_num = 0
        biggest_filled_tiles = None

        def do_fill(region, current_region_number):
            region.region_number = current_region_number

        for x in xrange(1, self.width - 1):
            for y in xrange(1, self.height - 1):
                if not self.tiles[x][y].blocks_mov and not self.tiles[x][y].region_number:
                    current_region_number += 1
                    filled_tiles = floodfill(fmap=self, x=x, y=y, do_fill=do_fill, do_fill_args=[current_region_number], is_border=lambda tile: tile.blocks_mov or tile.region_number)


                    if len(filled_tiles) > biggest_region_size:
                        biggest_region_size = len(filled_tiles)
                        biggest_region_num = current_region_number
                        biggest_filled_tiles = filled_tiles

        self.play_region = biggest_region_num
        self.play_tiles = tuple(biggest_filled_tiles)


    def generate_history(self, years):
        #self.generate_mythological_creatures()
        self.generate_sentient_races()
        self.generate_cultures()
        self.create_civ_cradle()
        self.settle_cultures()
        self.run_history(years)

        ## Add a "start playing" button if there isn't already one
        for button in panel2.wmap_buttons:
            if button.text == 'Start Playing':
                break
        else:
            panel2.wmap_buttons.append(gui.Button(gui_panel=panel2, func=g.game.new_game, args=[],
                                    text='Start Playing', topleft=(4, g.PANEL2_HEIGHT-16), width=20, height=5, color=g.PANEL_FRONT, do_draw_box=True))


    def generate_mythological_creatures(self):

        # Create a language for the culture to use
        language = lang.Language()
        self.languages.append(language)

        # Adding some ancient languages that are no longer spoken
        for i in xrange(5):
            ancient_language = lang.Language()
            self.ancient_languages.append(ancient_language)

        ## These guys will be less intelligent and more brute-ish. Generally live in lairs or move into existing empty structures
        num_brute_races = roll(3, 5)
        for i in xrange(num_brute_races):
            creature_name = language.gen_word(syllables=roll(1, 2), num_phonemes=(2, 10))
            # Shares physical components with humans for now
            phys_info = copy.deepcopy(phys.creature_dict['human'])

            description = gen_creatures.gen_creature_description(creature_name=lang.spec_cap(creature_name), creature_size=3)

            phys_info['name'] = creature_name
            # phys_info['char'] = creature_name[0].upper()
            phys_info['char'] = g.MYTHIC_TILE
            phys_info['description'] = description

            phys.creature_dict[creature_name] = phys_info
            self.brutish_races.append(creature_name)

            #g.game.add_message('- {0} added'.format(lang.spec_cap(creature_name)))

        self.default_mythic_culture = Culture(color=random.choice(g.CIV_COLORS), language=language, world=self, races=self.brutish_races)

        for site in self.all_sites:
            # Populate the cave with creatures
            if self.tiles[site.x][site.y].in_play_region() and site.type_ == 'cave' and roll(1, 10) >= 2:
                race = random.choice(self.brutish_races)
                name = self.default_mythic_culture.language.gen_word(syllables=roll(1, 2), num_phonemes=(2, 8))
                faction = Faction(leader_prefix=None, name=name, color=libtcod.black, succession='strongman', defaultly_hostile=1)
                born = g.WORLD.time_cycle.years_ago(50)
                myth_creature = self.default_mythic_culture.create_being(sex=1, born=born, char=g.MYTHIC_TILE, dynasty=None, important=1, faction=faction, wx=site.x, wy=site.y, armed=1, race=race, save_being=1, intelligence_level=2)

                num_creatures = roll(5, 25)
                sentients = {myth_creature.creature.culture:{myth_creature.creature.type_:{None:num_creatures}}}
                population = self.create_population(char=g.MYTHIC_TILE, name="myth creature group", faction=faction, creatures=None, sentients=sentients, econ_inventory={'food':1}, wx=site.x, wy=site.y, commander=myth_creature)


    def generate_sentient_races(self):
        ''' Generate some sentient races to populate the world. Very basic for now '''
        for i in xrange(5):
            # Throwaway language for now
            race_name_lang = lang.Language()
            creature_name = race_name_lang.gen_word(syllables=roll(1, 2), num_phonemes=(2, 20))
            # Shares physical components with humans for now
            phys_info = copy.deepcopy(phys.creature_dict['human'])

            description = gen_creatures.gen_creature_description(lang.spec_cap(creature_name))

            phys_info['name'] = creature_name
            phys_info['description'] = description

            phys.creature_dict[creature_name] = phys_info
            self.sentient_races.append(creature_name)

        g.game.add_message('{0} added'.format(join_list([lang.spec_cap(creature_name) for creature_name in self.sentient_races])))


    def generate_cultures(self):
        begin = time.time()

        number_of_cultures = roll(75, 100)
        ## Place some hunter-getherer cultures
        for i in xrange(number_of_cultures):
            # Random playable coords
            x, y = random.choice(self.play_tiles)
            # Make sure it's a legit tile and that no other culture owns it
            if not self.tiles[x][y].blocks_mov and self.tiles[x][y].culture is None:
                # spawn a culture
                language = lang.Language()
                self.languages.append(language)
                if roll(1, 10) > 2:
                    races = [random.choice(self.sentient_races)]
                else:
                    # Pick more than one race to be a part of this culture
                    races = []
                    for j in xrange(2):
                        while 1:
                            race = random.choice(self.sentient_races)
                            if race not in races:
                                races.append(race)
                                break

                culture = Culture(color=random.choice(g.CIV_COLORS), language=language, world=self, races=races)
                culture.edge = [(x, y)]
                culture.add_territory(x, y)
                self.cultures.append(culture)

        # Now, cultures expand organically
        expanded_cultures = self.cultures[:]
        while expanded_cultures:
            for culture in reversed(expanded_cultures):
                culture_expanded = culture.expand_culture_territory()

                if not culture_expanded:
                    expanded_cultures.remove(culture)

                    (cx, cy) = centroid(culture.territory)
                    culture.centroid = (int(cx), int(cy))
                    #self.tiles[culture.centroid[0]][culture.centroid[1]].color = libtcod.green

        ## Clean up ideal_locs a bit
        self.ideal_locs = filter(lambda (x, y): self.tiles[x][y].culture and not self.tiles[x][y].blocks_mov, self.ideal_locs)

        g.game.add_message('Cultures created in {0:.02f} seconds'.format(time.time() - begin))

        g.game.render_handler.render_all()

    def settle_cultures(self):
        '''Right now, a really simple and bad way to get some additional settlements'''
        for culture in self.cultures:
            if roll(1, 5) == 1:
                culture.add_villages()

                # Now that the band has some villages, it can change its subsistence strageties
                culture.set_subsistence(random.choice(('horticulturalist', 'pastoralist')))
                culture.create_culture_weapons()


    def create_civ_cradle(self):
        ''' Create a bundle of city states'''
        begin = time.time()

        ## Find an area where all resource types are available
        unavailable_resource_types = ['initial_dummy_value']
        while unavailable_resource_types:
            x, y = random.choice(self.ideal_locs)
            if self.is_valid_site(x, y, None, g.MIN_SITE_DIST):
                # Check for economy
                nearby_resources, nearby_resource_locations = self.find_nearby_resources(x=x, y=y, distance=g.MAX_ECONOMY_DISTANCE)
                ## Use nearby resource info to determine whether we can sustain an economy
                unavailable_resource_types = economy.check_strategic_resources(nearby_resources)

        # Seed with initial x, y value
        city_sites = [(x, y)]
        # Running list of created cities
        created_cities = []
        # Running list of cultures who have created cities
        civilized_cultures = []

        # Set world lingua franca
        self.lingua_franca = self.tiles[x][y].culture.language

        #city_blocker_resources = ('copper', 'bronze', 'iron')

        while city_sites != []:
            nx, ny = random.choice(city_sites)
            city_sites.remove((nx, ny))

            # Can't add this jitter yet, since changing the placement of the city can cause it to miss out on other resources
            #for resource in g.WORLD.tiles[nx][ny].res:
            #    if resource in city_blocker_resources:
            #        (nx, ny) = random.choice([t for t in get_border_tiles(nx, ny) if self.is_valid_site(t[0], t[1]) ])
            #        break

            if self.tiles[nx][ny].site:
                continue

            #### Create a civilization #####
            culture = g.WORLD.tiles[nx][ny].culture

            civ_color = random.choice(g.CIV_COLORS)
            name = lang.spec_cap(self.tiles[nx][ny].culture.language.gen_word(syllables=roll(1, 2), num_phonemes=(2, 20)))

            profession = Profession(name='King', category='noble')
            city_faction = Faction(leader_prefix='King', name='City of %s'%name, color=civ_color, succession='dynasty')

            leader, all_new_figures = culture.create_initial_dynasty(faction=city_faction, wx=nx, wy=ny, wife_is_new_dynasty=1)

            city = self.make_city(cx=nx, cy=ny, char=g.CITY_TILE, color=civ_color, name=name)
            city.set_leader(leader)
            for entity in all_new_figures:
                city.add_citizen(entity=entity)

            city.setup_initial_buildings()

            ### Add initial leader and dynasty ####
            city_faction.set_leader(leader)
            profession.give_profession_to(figure=leader)
            profession.set_building(building=city.get_building(building_name='City Hall'))

            created_cities.append(city)
            ####################################

            # Setup satellites around the city #
            for rx, ry in nearby_resource_locations:
                for xx, yy in [(city.x, city.y) for city in created_cities] + city_sites:
                    if get_distance_to(xx, yy, rx, ry) <= 3:
                        break
                ## Add to cities if it's not too close
                else:
                    city_sites.append((rx, ry))

        ## This is a quick fix for cases where the economy module has detected some nearby resources which
        ## may be essential for the full economy, but for some reason a city couldn't be built nearby. For
        ## now, we just let the closest city to an unclaimed resource location acquire that region.
        for rx, ry in nearby_resource_locations:
            if not self.tiles[rx][ry].territory:
                city = self.get_closest_city(x=rx, y=ry)[0]
                city.acquire_tile(rx, ry)
                logging.debug('{0} has expanded its territory for {1}'.format(city.get_name(), join_list(self.tiles[rx][ry].res.keys())) )

        ## We assume the domestication of food has spread to all nearby cities
        for city in created_cities:
            if not 'food' in city.native_res:
                city.native_res['food'] = 2000
            if not 'flax' in city.native_res:
                g.WORLD.tiles[city.x][city.y].add_resource('flax', 2000)
                city.native_res['flax'] = 2000

            if g.WORLD.tiles[city.x][city.y].culture.subsistence != 'agricultural':
                g.WORLD.tiles[city.x][city.y].culture.set_subsistence('agricultural')

            # Make sure the cultures the cities are a part of gain access to the resource
            for resource in self.tiles[city.x][city.y].res:
                if resource not in self.tiles[city.x][city.y].culture.access_res:
                    self.tiles[city.x][city.y].culture.access_res.append(resource)

            if city.get_culture() not in civilized_cultures:
                civilized_cultures.append(city.get_culture())

        ## The cultures surrounding the cities now fill in with villages, sort of
        for culture in civilized_cultures:
            # Add some more gods to their pantheons, and update the relationships between them
            culture.pantheon.create_misc_gods(num_misc_gods=roll(4, 6))
            culture.pantheon.update_god_relationships()

            #### Give the culture's pantheon a holy object ####
            object_blueprint = phys.object_dict['holy relic']
            material = data.commodity_manager.materials['copper']
            initial_location = random.choice(culture.territory)
            obj = assemble_object(object_blueprint=object_blueprint, force_material=material, wx=initial_location[0], wy=initial_location[1])
            culture.pantheon.add_holy_object(obj)
            self.add_famous_object(obj=obj)

            # Object will be put inside a temple
            housed_city = random.choice(filter(lambda city_: city_.get_culture() == culture, created_cities))
            temple = housed_city.get_building('Temple')
            obj.set_current_building(building=temple)

            # Object will be owned by the High Priest
            for worker in temple.current_workers:
                if worker.creature.profession.name == 'High Priest':
                    obj.set_current_owner(worker)
                    break

            # The culture can add some other villages nearby
            culture.add_villages()


        ## Add appropriate imports and exports (can be re-written to be much more efficient...)
        for city in created_cities:
            # At this point, we should have no imports, but just in case... flatten the list
            flattened_import_list = city.get_all_imports()
            ## Make a list of other cities by distance, so you can import from the closer cities first
            # cities_and_distances = [(city.distance_to(c), c) for c in created_cities if c != city]
            cities_and_distances = [(self.get_astar_distance_to(city.x, city.y, c.x, c.y), c) for c in created_cities if c != city]

            cities_and_distances.sort()

            for distance, other_city in cities_and_distances:
                for resource in other_city.native_res:
                    # If they have stuff we don't have access to and are not currently importing...
                    if resource not in city.native_res and resource not in flattened_import_list:
                        # Import it!
                        city.add_import(other_city, resource)
                        other_city.add_export(city, resource)
                        ## Update the import list because we are now importing stuff
                        flattened_import_list.append(resource)

        ## Ugly ugly road code for now
        for city in created_cities:
            closest_ucity = self.get_closest_city(city.x, city.y, 100)[0]
            if closest_ucity not in city.connected_to:
                city.build_road_to(closest_ucity.x, closest_ucity.y)
                city.connect_to(closest_ucity)

        ###################################
        ###### This code makes me cry   ###
        ###################################
        city_list = created_cities[:]
        clumped_cities = []

        # Keep going until city list is empty
        while len(city_list):
            # Pick the first city
            city_clump = []
            untested_cities = [city_list[0]]
            while len(untested_cities):

                ucity = untested_cities.pop(0)
                city_list.remove(ucity)
                city_clump.append(ucity)

                for ccity in ucity.connected_to:
                    if ccity not in city_clump and ccity in city_list:

                        untested_cities.append(ccity)

            # Once there are no more connections,they form a clump
            clumped_cities.append(city_clump)

        ## Time to create the actual network. Here we search for clumps of cities
        ## which have not been joined together, and join them at their closest cities
        networked_cities = clumped_cities.pop(0)

        while len(clumped_cities):
            other_clump = clumped_cities.pop(0)

            c1, c2 = self.find_closest_clumped_cities(networked_cities, other_clump)

            if c1 is not None:
                c1.build_road_to(c2.x, c2.y)
                c1.connect_to(c2)

                for ocity in other_clump:
                    networked_cities.append(ocity)
        ################################################################################

        # Make libtcod path map, where only roads are walkable
        self.refresh_road_network(networked_cities)

        # Time to go through and see if we can create slightly more efficient paths from city to city
        for city, other_city in itertools.combinations(networked_cities, 2):
            current_path_len = max(len(city.path_to[other_city]), 1)

            new_path_len = self.get_astar_distance_to(city.x, city.y, other_city.x, other_city.y)

            # Ratio of < 1 means that the new path was shorter than the existing road path
            ratio = new_path_len / current_path_len

            if ratio <= g.NEW_ROAD_PATH_RATIO:
                # Build a new road
                city.build_road_to(other_city.x, other_city.y, libtcod.black)
                city.connect_to(other_city)
                # Translate and save libtcod paths
                path_to_other_city = libtcod_path_to_list(path_map=self.road_path_map)

                # Kill 2 birds with one stone (sort of)
                other_city_path_to_us = path_to_other_city[:]
                other_city_path_to_us.reverse()

                city.path_to[other_city] = path_to_other_city
                other_city.path_to[city] = other_city_path_to_us
                # Now that the road has been built, other cities can use it to path to yet more cities
                self.refresh_road_network(networked_cities)

        for city, other_city in itertools.combinations(networked_cities, 2):
            path = city.path_to[other_city]
            for (x, y) in path:

                if self.tiles[x][y].has_feature('road'):
                    self.set_road_tile(x, y)

                # This will update the graphic on the border tile to make it "connect" to the current road
                for xx, yy in get_border_tiles(x, y):
                    if self.tiles[xx][yy].has_feature('road'):
                        self.set_road_tile(xx, yy)

        ## Now setup the economy since we have all import/export info
        for city in created_cities:
            # This doesn't necessarily have to be done here, but we should add shrines around the city
            x, y = roll(city.x-5, city.x+5), roll(city.y-5, city.y+5)
            # Loop should only get here if no site is added, due to the continue syntax
            if self.is_valid_site(x=x, y=y, civ=city) and roll(1, 10) >= 8:
                self.add_shrine(x, y, city)

        for city in created_cities:
            city.prepare_native_economy()

        for city in created_cities:
            city.setup_native_economy()

        for city in created_cities:
            city.setup_imports()

        for city in created_cities:
            city.get_faction().create_faction_objects()
            # Now that imports have been created (last loop) we can start cache-ing the objects available here
            city.update_object_to_agents_dict()

        ## Make sure succession gets set up
        for faction in self.factions:
            faction.get_heirs(3)

        # For now, just add some ruins in some unused possible city slots
        for x, y in self.ideal_locs:
            if self.is_valid_site(x, y, None, g.MIN_SITE_DIST):
                self.add_ruins(x, y)

        target_nodes = [(city.x, city.y) for city in created_cities]
        self.distance_from_civilization_dmap = Dijmap(sourcemap=self, target_nodes=target_nodes, dmrange=10000)

        # Each city gets a few bandits near it
        self.add_bandits(city_list=networked_cities, lnum=0, hnum=2, radius=10)


        ############################################################################################
        # As a final cleanup step, add knowledge to characters who were created earlier in history #
        ############################################################################################

        # Prepare a list of all nearby chunks, which will be used to fuel cultural knowledgte of nearby sites
        all_nearby_chunks = []
        for city in created_cities:
            nearby_chunks = self.get_nearby_chunks(chunk=self.tiles[city.x][city.y].chunk, distance=1)
            for chunk in nearby_chunks:
                if chunk not in all_nearby_chunks:
                    all_nearby_chunks.append(chunk)

        # On this step, explicitly add knowledge of all the sites nearby to this chunk
        for city in created_cities:
            for chunk in all_nearby_chunks:
                for site in chunk.get_all_sites():
                    city.get_culture().add_c_knowledge_of_site(site=site, location_accuracy=5)

        # Until this point, a bunch of creature have been created, but their knowledge base needs to be updated with the new sites
        for entity in g.WORLD.all_figures:
            entity.creature.culture.transfer_c_knowledge_to_entity(entity=entity, date=entity.creature.born)

            # It may not be cultural, but still give other entities knowledge of nearby sites
            if entity.creature.culture not in civilized_cultures:
                nearby_chunks = self.get_nearby_chunks(chunk=self.tiles[entity.wx][entity.wy].chunk, distance=1)
                for chunk in nearby_chunks:
                    for site in chunk.get_all_sites():
                        entity.creature.add_knowledge_of_site(site=site, date_learned=entity.creature.born, source=entity, location_accuracy=5)


        # Some history books
        date = g.WORLD.time_cycle.get_current_date()

        for city in created_cities:
            c_language = city.get_culture().language
            #### Book ####
            book = assemble_object(object_blueprint=phys.object_dict['book'], force_material=data.commodity_manager.materials['wood'], wx=city.x, wy=city.y)

            for event in hist.historical_events:
                book.components[0].add_information_of_event(language=c_language, event_id=event.id_, date_written=date, author=None, location_accuracy=1)

            book.interactable = {'func':book.read_information, 'args':[], 'text':'Read {0}'.format(book.name), 'hover_text':['Cave entrance']}
            self.add_famous_object(obj=book)
            city_hall = city.get_building('City Hall')
            book.set_current_building(building=city_hall)

            #### Map ####
            map_ = assemble_object(object_blueprint=phys.object_dict['map'], force_material=data.commodity_manager.materials['wood'], wx=city.x, wy=city.y)

            for site in g.WORLD.sites:
                map_.components[0].add_information_of_site(language=c_language, site=site, date_written=date, author=None, location_accuracy=5, is_part_of_map=1, describe_site=0)

            map_.interactable = {'func':map_.read_information, 'args':[], 'text':'Read {0}'.format(map_.name), 'hover_text':['Cave entrance']}
            self.add_famous_object(obj=map_)
            city_hall = city.get_building('City Hall')
            map_.set_current_building(building=city_hall)

            # Object will be owned by the High Priest
            #for worker in city_hall.current_workers:
            #    if worker.creature.profession.name == 'King':
            #        obj.set_current_owner(worker)
            #        break

        ### Set some ancient maps to appear, in ancient languages
        potential_map_sites = {'cave':5, 'ancient settlement':100}
        for site in self.all_sites:
            if site.type_ in potential_map_sites and roll(1, 100) < potential_map_sites[site.type_]:
                language = random.choice(self.ancient_languages)
                # Create a map
                map_ = assemble_object(object_blueprint=phys.object_dict['map'], force_material=data.commodity_manager.materials['wood'], wx=site.x, wy=site.y)
                # Find info for map
                for chunk in self.get_nearby_chunks(chunk=self.tiles[site.x][site.y].chunk, distance=1):
                    for other_site in chunk.get_all_sites():
                        if roll(1, 100) < 90:
                            map_.components[0].add_information_of_site(language=language, site=other_site, date_written=date, author=None, location_accuracy=5, is_part_of_map=1, describe_site=0)

                # Set map's interactivity
                map_.interactable = {'func':map_.read_information, 'args':[], 'text':'Read {0}'.format(map_.name), 'hover_text':['Map']}

                if site.buildings:
                    map_.set_current_building(building=random.choice(site.buildings))

        # Some timing and debug info
        #g.game.add_message('Civs created in %.2f seconds' %(time.time() - begin))
        #g.game.add_message('%i dynasties so far...' %len(self.dynasties), libtcod.grey)

        g.game.render_handler.render_all()


    def refresh_road_network(self, cities):
        #for i, city in enumerate(networked_cities):
        #    for other_city in networked_cities[i+1:]:
        for city, other_city in itertools.permutations(cities, 2):
            # Compute path to other
            road_path = libtcod.path_compute(self.road_path_map, city.x, city.y, other_city.x, other_city.y)
            # Walk through path and save as a list
            x = 1
            path_to_other_city = []

            while x is not None:
                x, y = libtcod.path_walk(self.road_path_map, True)

                if x is not None:
                    path_to_other_city.append((x, y))

            #other_city_path_to_us = path_to_other_city[:]
            #other_city_path_to_us.reverse()

            # Now we know how to get from one city to another
            city.path_to[other_city] = path_to_other_city
            #other_city.path_to[city] = other_city_path_to_us


    def find_closest_clumped_cities(self, clump1, clump2):
        ''' For 2 lists of cities, find the two closest ones '''
        cities = (None, None)
        dist = 10000

        for city in clump1:
            for ocity in clump2:
                road_path = libtcod.path_compute(self.path_map, city.x, city.y, ocity.x, ocity.y)
                ## Why the hell do you have to use the path map variable here?
                pdist = libtcod.path_size(self.path_map)

                if pdist < dist:
                    dist = pdist
                    cities = (city, ocity)

        return cities

    def add_bandits(self, city_list, lnum, hnum, radius):
        ''' Bandits will search for a suitable site to move into, or else they will build their own '''

        force_steal = 1
        for city in city_list:
            # Bandits may try to steal holy objects
            possible_obj_to_steal = None
            temple = city.get_building('Temple')
            for obj in self.famous_objects:
                if obj in temple.housed_objects:
                    possible_obj_to_steal = obj
                    break

            # Each city gets a certain number of nearby hideouts
            hideout_num = roll(lnum, hnum)

            # Build a list of possible sites to move into
            possible_sites = []
            for x in xrange(city.x-radius, city.x+radius):
                for y in xrange(city.y-radius, city.y+radius):
                    # Make sure there is a valid path to the city
                    if self.get_astar_distance_to(x, y, city.x, city.y) is not None:
                        # Add caves and ruins
                        possible_sites.extend(self.tiles[x][y].caves)
                        if self.tiles[x][y].site and self.tiles[x][y].site.type_ == 'ruins':
                            possible_sites.append(self.tiles[x][y].site)

            # Attempt to place them in existing sites
            while len(possible_sites) and hideout_num:
                possible_site = possible_sites.pop(roll(0, len(possible_sites)-1 ))

                if possible_site.get_faction() is None:
                    ## Right now creating a dummy building. Eventually we won't need to do this, since sites will have their own buildings already present
                    possible_site.create_building(zone='residential', type_='hideout', template='TEST', professions=[], inhabitants=[], tax_status=None)
                    leader = self.create_and_move_bandits_to_site(wx=possible_site.x, wy=possible_site.y, hideout_site=possible_site)

                    g.game.add_message('Bandits moving to %s'%possible_site.type_, libtcod.dark_grey)

                    # For now, chance of stealing holy relic and taking it to the site
                    # if possible_obj_to_steal and (roll(0, 1) or (force_steal and possible_site.type_ == 'cave')):
                    #     # Flip off flag so future steals are left to chance0
                    #     force_steal = 0
                    #
                    #     possible_obj_to_steal.set_current_owner(leader)
                    #     possible_obj_to_steal.set_current_building(hideout_building)
                    #     #g.game.add_message('%s, Bandit leader moved to %s and has stolen %s' %(leader.fullname(), possible_site.get_name(), possible_obj_to_steal.fullname()), libtcod.orange)
                    #     possible_obj_to_steal = None
                    # else:
                    #     pass
                    #     #g.game.add_message('%s, Bandit leader moved to %s' %(leader.fullname(), possible_site.get_name()), libtcod.orange)

                    hideout_num -= 1

            # Otherwise, they can build their own little shacks
            for i in xrange(hideout_num):
                # Pick a good spot
                iter = 0
                while True:
                    iter += 1
                    if iter > 20:
                        logging.debug('couldn\'t find good spot for bandits')
                        break
                    # Hideout is min 4 distance away
                    xd = roll(4, 8) * random.choice((-1, 1))
                    yd = roll(4, 8) * random.choice((-1, 1))
                    x, y = city.x + xd, city.y + yd
                    # If it's a valid spot, place the hideout
                    if self.is_val_xy((x, y)) and self.is_valid_site(x, y) and not self.tiles[x][y].has_feature('road') and self.get_astar_distance_to(city.x, city.y, x, y):
                        # Will add a hideout building here
                        self.create_and_move_bandits_to_site(wx=x, wy=y, hideout_site=None)
                        g.game.add_message('Bandits moving to their own site', libtcod.dark_grey)
                        break


    def run_history(self, weeks):
        ## Some history...
        #begin = time.time()
        for i in xrange(weeks * 7):
            self.time_cycle.day_tick()
        #g.game.add_message('History run in %.2f seconds' %(time.time() - begin))
        # List the count of site types
        g.game.add_message(join_list([ ct(type_, len(self.site_index[type_])) for type_ in self.site_index]))


    def initialize_fov(self):
        ## Field of view / pathfinding modules
        self.fov_recompute = True

        self.fov_map = libtcod.map_new(self.width, self.height)
        for y in range(self.height):
            for x in range(self.width):
                libtcod.map_set_properties(self.fov_map, x, y, not self.tiles[x][y].blocks_vis, not self.tiles[x][y].blocks_mov)
        self.path_map = libtcod.path_new_using_map(self.fov_map)

        # New map that disallows diagonals - used for roads
        self.rook_path_map = libtcod.path_new_using_map(self.fov_map, 0.0)

        # Build FOV map - only roads are walkable here! (will refresh each time a road is built)
        self.road_fov_map = libtcod.map_new(self.width, self.height)

        for x in xrange(self.width):
            for y in xrange(self.height):
                libtcod.map_set_properties(self.road_fov_map, x, y, 1, 0)
        self.road_path_map = libtcod.path_new_using_map(self.road_fov_map)

    def display(self):
        ''' Display the world '''
        if g.game.world_map_display_type == 'normal':
            #buffer = libtcod.ConsoleBuffer(CAMERA_WIDTH, CAMERA_HEIGHT)

            ##### Micro-optimizations to avoid lookups in the loop
            tiles = self.tiles
            con = g.game.interface.map_console.con
            render_tile = g.game.render_handler.render_tile
            ##### End micro-optimizations

            for x, y, mx, my in g.game.camera.get_xy_for_rendering():
                render_tile(con, x, y, tiles[mx][my].char, tiles[mx][my].char_color, tiles[mx][my].color)

                #bc = g.WORLD.tiles[wmap_x][wmap_y].color
                #fc = g.WORLD.tiles[wmap_x][wmap_y].char_color
                #buffer.set(x=x, y=y, back_r=g.WORLD.tiles[wmap_x][wmap_y].color.r, back_g=g.WORLD.tiles[wmap_x][wmap_y].color.g, back_b=g.WORLD.tiles[wmap_x][wmap_y].color.b, \
                #            fore_r=g.WORLD.tiles[wmap_x][wmap_y].char_color.r, fore_g=g.WORLD.tiles[wmap_x][wmap_y].char_color.g, fore_b=g.WORLD.tiles[wmap_x][wmap_y].char_color.b, char=g.WORLD.tiles[wmap_x][wmap_y].char)

            #buffer.blit(con.con)

        elif g.game.world_map_display_type == 'culture':
            for x, y, mx, my in g.game.camera.get_xy_for_rendering():
                if self.tiles[mx][my].culture is not None:
                    color = self.tiles[mx][my].culture.color
                    g.game.render_handler.render_tile(g.game.interface.map_console.con, x, y, 255, color, color * 1.2)

                else:
                    g.game.render_handler.render_tile(g.game.interface.map_console.con, x, y, self.tiles[mx][my].char, self.tiles[mx][my].char_color, self.tiles[mx][my].color)

        ######################### Territories ##################################
        elif g.game.world_map_display_type == 'territory':
            for x, y, mx, my in g.game.camera.get_xy_for_rendering():
                if self.tiles[mx][my].territory is not None:
                    color = self.tiles[mx][my].territory.color
                    g.game.render_handler.render_tile(g.game.interface.map_console.con, x, y, 255, color, color * 1.5)

                else:
                    g.game.render_handler.render_tile(g.game.interface.map_console.con, x, y, self.tiles[mx][my].char, self.tiles[mx][my].char_color, self.tiles[mx][my].color)

        ######################### Resources ##################################
        elif g.game.world_map_display_type == 'resource':
            for x, y, mx, my in g.game.camera.get_xy_for_rendering():
                g.game.render_handler.render_tile(g.game.interface.map_console.con, x, y, self.tiles[mx][my].char, self.tiles[mx][my].char_color, self.tiles[mx][my].color)

                if self.tiles[mx][my].res and not 'wood' in self.tiles[mx][my].res:
                    # TODO - convert this to actual tiles and not half-tiles
                    char = ord(self.tiles[mx][my].res.keys()[0][0].capitalize())
                    libtcod.console_put_char_ex(g.game.interface.map_console.con, x, y, char, libtcod.green, libtcod.black)
                    libtcod.console_put_char_ex(g.game.interface.map_console.con, x+1, y, g.EMPTY_TILE, libtcod.green, libtcod.black)
        ###########################################################################

        self.draw_world_objects()
        #blit the contents of "con.con" to the root console
        g.game.interface.map_console.blit()


    def is_valid_site(self, x, y, civ=None, min_dist=None):
        # Checks if site is a valid spot to build a city
        # Can't build if too close to another city, and if the territory alread belongs to someone else
        if min_dist is not None:
            for site in self.sites:
                if site.distance(x, y) < min_dist:
                    return False

        return not (self.tiles[x][y].blocks_mov) and (not self.tiles[x][y].site) and (self.tiles[x][y].territory is None or self.tiles[x][y].territory == civ)


    def closest_city(self, user, max_range, target_faction=None):
        closest_city = None
        closest_dist = max_range + 1  #start with (slightly more than) maximum range

        for city in self.cities:
            if target_faction is None or city.owner == target_faction:
                dist = self.get_astar_distance_to(user.x, user.y, city.x, city.y)
                if dist < closest_dist:  #it's closer, so remember it
                    closest_city = city
                    closest_dist = dist
        return closest_city


    def check_for_encounters(self):
        ''' Loops through all tiles in the world which have been marked as potential encounter zones and checks to see if
            any need to run encounters. This could be a battle if the factions are hostile, or just an exchange of information
            if not '''

        # Loop through all tiles that have been flagged
        for tile in self.tiles_with_potential_encounters:
            wx, wy = tile.x, tile.y

            factions_and_entities = defaultdict(list)
            for entity in tile.entities:
                factions_and_entities[entity.creature.faction].append(entity)

            for faction, other_faction in itertools.combinations(factions_and_entities.keys(), 2):
                # Do battle if the two factions are hostile
                if faction.is_hostile_to(other_faction):
                    ## TODO - clean up ugly list comprehensions and whatnot
                    faction_named = [e for e in factions_and_entities[faction] if e.creature.is_available_to_act()]
                    faction_populations = [p for p in tile.populations if p.faction == faction]

                    other_faction_named = [e for e in factions_and_entities[other_faction] if e.creature.is_available_to_act()]
                    other_faction_populations = [p for p in tile.populations if p.faction == other_faction]

                    if faction_named and other_faction_named and not g.player in faction_named + other_faction_named:
                        # This will resolve the battle
                        battle = combat.WorldBattle(g.WORLD.time_cycle.get_current_date(), location=(wx, wy),
                                                    faction1_named=faction_named, faction1_populations=faction_populations,
                                                    faction2_named=other_faction_named, faction2_populations=other_faction_populations)

                        g.game.add_message(battle.describe(), libtcod.color_lerp(g.PANEL_FRONT, faction_named[0].color, .3))

            # Each entity also has a chance of talking to other ones
            for entity1, entity2 in itertools.combinations(tile.entities, 2):
                # TODO - should have a chance of spreading rumors too
                if (entity1.creature.important or entity2.creature.important) and not entity1.creature.faction.is_hostile_to(entity2.creature.faction):
                    entity1.creature.encounter(other=entity2)
                    entity2.creature.encounter(other=entity1)

        # Reset those tiles
        self.tiles_with_potential_encounters = set([])

    def goto_scale_map(self):
        ''' Create battle map from g.player's world coords '''
        global M
        g.game.switch_map_scale(map_scale='human')

        x, y = g.player.wx, g.player.wy

        ## Set size of map
        if self.tiles[x][y].site and self.tiles[x][y].site.type_ == 'city':
            g.M = Wmap(world=self, wx=x, wy=y, width=g.CITY_MAP_WIDTH, height=g.CITY_MAP_HEIGHT)
        else:
            g.M = Wmap(world=self, wx=x, wy=y, width=g.MAP_WIDTH, height=g.MAP_HEIGHT)



        # Make map
        if self.tiles[x][y].site and self.tiles[x][y].site.type_ == 'city':
            hm = g.M.create_heightmap_from_surrounding_tiles(minh=1, maxh=4, iterations=20)
            g.M.create_map_tiles(hm=hm, base_color=self.tiles[x][y].get_base_color(), explored=1)

            g.M.make_city_map(site=self.tiles[x][y].site, num_nodes=22, min_dist=35, disorg=5)

        elif self.tiles[x][y].site and self.tiles[x][y].site.type_ == 'village':
            hm = g.M.create_heightmap_from_surrounding_tiles(minh=1, maxh=4, iterations=20)
            g.M.create_map_tiles(hm=hm, base_color=self.tiles[x][y].get_base_color(), explored=1)

            g.M.make_city_map(site=self.tiles[x][y].site, num_nodes=10, min_dist=15, disorg=10)

        else:
            hm = g.M.create_heightmap_from_surrounding_tiles()
            base_color = self.tiles[x][y].get_base_color()
            g.M.create_map_tiles(hm, base_color, explored=1)



        g.M.run_cellular_automata(cfg=g.MCFG[self.tiles[x][y].region])
        g.M.add_minor_sites_to_map()

        if not self.tiles[x][y].site:
            g.M.add_world_features(x, y)

        ########### NATURE #################
        g.M.color_blocked_tiles(cfg=g.MCFG[self.tiles[x][y].region])
        g.M.add_vegetation(cfg=g.MCFG[self.tiles[x][y].region])
        g.M.set_initial_dmaps()

        g.M.add_sapients_to_map(entities=g.WORLD.tiles[x][y].entities, populations=g.WORLD.tiles[x][y].populations)

        g.game.camera.center(g.player.x, g.player.y)
        g.game.handle_fov_recompute()


    def make_cave_map(self, wx, wy, cave):

        base_color = libtcod.color_lerp(libtcod.darkest_grey, libtcod.darker_sepia, .5)

        cfg ={
             'initial_blocks_mov_chance':550,
             'repetitions':2,
             'walls_to_floor':3,
             'walls_to_wall':5,
             'blocks_mov_color':libtcod.darkest_grey,
             'blocks_mov_surface':'cave wall',
             'shade':1,
             'blocks_mov_height':189,

             'small_tree_chance':0,
             'small_stump_chance':0,
             'large_tree_chance':0,
             'large_stump_chance':0,
             'shrub_chance':10,
             'unique_ground_tiles':(()),
             'map_pad':6,
             'map_pad_type':1
             }


        width, height = 150, 150

        target_unfilled_cells = int(width*height/3)
        num_remaining_open_tiles = 0
        rejections = -1
        # Sometimes cellular automata will generate small pockets of unconnected regions; here we will ensure a certain amount of contiguous open cells
        while num_remaining_open_tiles < target_unfilled_cells:
            rejections += 1

            g.M = None
            g.M = Wmap(world=self, wx=wx, wy=wy, width=width, height=height)
            hm = g.M.create_and_vary_heightmap(initial_height=110, mborder=20, minr=20, maxr=35, minh=-6, maxh=8, iterations=50)
            g.M.create_map_tiles(hm=hm, base_color=base_color, explored=0)

            g.M.run_cellular_automata(cfg=cfg)

            ## Add some drunk walkers!
            dcfg = {'bias':None, 'color':base_color, 'empty_stop':False, 'tile_limit':1000}
            for i in xrange(5):
                walker = DrunkWalker(umap=g.M, x=roll(20, g.M.width-21), y=roll(20, g.M.height-21), cfg=dcfg)
                walker.drunk_walk()

            ### This step fills in every pocket of open ground that's not connected to the largest open pocket
            remaining_open_tiles, fill_counter = g.M.fill_open_pockets(target_unfilled_cells)
            num_remaining_open_tiles = len(remaining_open_tiles)

        g.game.add_message('%i rejections; filled %i openings' %(rejections, fill_counter), libtcod.dark_green)

        ############ Cave entrance - generated by drunk walker ######################
        entry_dict = {
                      'n':{'coords':(roll(10, g.M.width-11), 1), 'bias_dir':0},
                      'e':{'coords':(g.M.width-2, roll(10, g.M.height-11) ), 'bias_dir':3},
                      's':{'coords':(roll(10, g.M.width-11), g.M.height-2), 'bias_dir':2},
                      'w':{'coords':(1, roll(10, g.M.height-11) ), 'bias_dir':1}
                      }

        entry_dir = random.choice(entry_dict.keys())
        x, y = entry_dict[entry_dir]['coords']
        bias_dir = entry_dict[entry_dir]['bias_dir']

        dcfg = {'bias':(bias_dir, 200), 'color':base_color, 'empty_stop':True, 'tile_limit':-1}
        walker = DrunkWalker(umap=g.M, x=x, y=y, cfg=dcfg)
        walker.drunk_walk()
        ##############################################################################
        g.M.add_dmap(key='exit', target_nodes=[(x, y)], dmrange=5000)

        distance_from_exit = 100


        # Add each building to the cave
        for building in cave.buildings:
            # Pick a random area until one is not blocks_mov and at least distance_from_exit from the exit
            while 1:
                bx, by = roll(5, g.M.width-6), roll(5, g.M.height-6)
                if (not g.M.tile_blocks_mov(bx, by)) and g.M.dijmaps['exit'].dmap[bx][by] > distance_from_exit :

                    def do_fill(tile, building):
                        tile.building = building
                        tile.set_color(libtcod.color_lerp(tile.color, libtcod.grey, .1))

                    filled = floodfill(fmap=g.M, x=bx, y=by, do_fill=do_fill, do_fill_args=[building], is_border=lambda tile: tile.blocks_mov or tile.building, max_tiles=100)

                    for xx, yy in filled:
                        building.physical_property.append((xx, yy))
                    break

            # Add building garrisons
            for army in building.garrison:
                army.add_to_map(startrect=None, startbuilding=building, patrol_locations=[random.choice(building.physical_property)])

            # Finally add any housed objects to the map
            building.add_housed_objects_to_map()

        ########### NATURE #################
        g.M.color_blocked_tiles(cfg=cfg)
        g.M.add_vegetation(cfg=cfg)
        g.M.set_initial_dmaps()
        g.M.add_object_to_map(x=x, y=y, obj=g.player)

        ## DIJMAP
        g.M.cache_factions_for_dmap()
        ######################################

        g.M.initialize_fov()
        g.game.camera.center(g.player.x, g.player.y)
        g.game.handle_fov_recompute()

    def make_city(self, cx, cy, char, color, name):
        # Make a city
        city = City(world=self, type_='city', x=cx, y=cy, char=char, name=name, color=color)

        self.tiles[cx][cy].site = city
        self.tiles[cx][cy].all_sites.append(city)

        self.tiles[cx][cy].chunk.add_site(city)
        self.make_world_road(cx, cy)

        self.sites.append(city)
        self.cities.append(city)
        self.all_sites.append(city)

        return city

    def add_mine(self, x, y, city):
        mine = self.tiles[x][y].create_and_add_minor_site(world=self, type_='mine', char=g.MINE_TILE, name=None, color=city.get_faction().color)
        mine.create_building(zone='residential', type_='hideout', template='TEST', professions=[], inhabitants=[], tax_status=None)
        self.tiles[x][y].char = g.MINE_TILE
        self.tiles[x][y].char_color = city.get_faction().color

        return mine

    def add_farm(self, x, y, city):
        farm = self.tiles[x][y].create_and_add_minor_site(world=self, type_='farm', char=g.FARM_TILE, name=None, color=city.get_faction().color)
        farm.create_building(zone='residential', type_='hideout', template='TEST', professions=[], inhabitants=[], tax_status=None)
        if not self.tiles[x][y].has_feature('road'):
            self.tiles[x][y].char = g.FARM_TILE
            self.tiles[x][y].char_color = city.get_faction().color

        return farm

    def add_shrine(self, x, y, city):
        name = '{0} shrine'.format(city.get_culture().pantheon.name)
        shrine = self.tiles[x][y].create_and_add_minor_site(world=self, type_='shrine', char=g.SHRINE_TILE, name=name, color=libtcod.black)
        shrine.create_building(zone='residential', type_='hideout', template='TEST', professions=[], inhabitants=[], tax_status=None)
        self.tiles[x][y].char = g.SHRINE_TILE
        self.tiles[x][y].char_color = libtcod.black

        city.get_culture().pantheon.add_holy_site(shrine)

        return shrine

    def add_ruins(self, x, y):
        # Make ruins
        site_name = self.tiles[x][y].culture.language.gen_word(syllables=roll(1, 2), num_phonemes=(3, 20))
        name = lang.spec_cap(site_name)

        ruin_site = self.tiles[x][y].create_and_add_minor_site(world=self, type_='ancient settlement', char=g.RUINS_TILE, name=name, color=libtcod.black)
        self.tiles[x][y].chunk.add_site(ruin_site)

        self.tiles[x][y].char = g.RUINS_TILE
        self.tiles[x][y].char_color = libtcod.black
        for i in xrange(roll(1, 3)):
            building = ruin_site.create_building(zone='residential', type_='hideout', template='TEST', professions=[], inhabitants=[], tax_status=None)


        # Move some unintelligent creatures in if it's near cities
        if 0 < self.get_astar_distance_to(x, y, self.site_index['city'][0].x, self.site_index['city'][0].y) < 45: #roll(0, 1):
            race_name = random.choice(self.brutish_races)
            name = '{0} raiders'.format(race_name)
            faction = Faction(leader_prefix='Chief', name='{0} of {1}'.format(pl(race_name, num=2), site_name), color=libtcod.black, succession='strongman', defaultly_hostile=1)
            culture = Culture(color=libtcod.black, language=random.choice(self.languages), world=self, races=[race_name])

            born = g.WORLD.time_cycle.years_ago(roll(20, 45))
            leader = culture.create_being(sex=1, born=born, dynasty=None, important=0, faction=faction, wx=x, wy=y, armed=1, save_being=1, intelligence_level=2)
            faction.set_leader(leader)

            sentients = {leader.creature.culture:{leader.creature.type_:{'Swordsman':10}}}
            self.create_population(char='u', name=name, faction=faction, creatures={}, sentients=sentients, econ_inventory={'food':1}, wx=x, wy=y, site=ruin_site, commander=leader)
            # Set the headquarters and update the title to the building last created.
            if roll(1, 10) >= 9:
                closest_city = self.get_closest_city(x, y)[0]
                closest_city.get_culture().pantheon.add_holy_site(ruin_site)

        return ruin_site


    def create_and_move_bandits_to_site(self, wx, wy, hideout_site):
        ''' Creates a group of bandits to move to an uninhabited site '''

        closest_city = self.get_closest_city(wx, wy)[0]
        if closest_city is None:
            closest_city = random.choice(self.cities)
            logging.debug('Bandits could not find closest city')

        # bname = lang.spec_cap(closest_city.get_culture().language.gen_word(syllables=roll(1, 2), num_phonemes=(3, 20)) + ' bandits')
        bname = lang.spec_cap(closest_city.get_culture().language.gen_word(syllables=roll(1, 2), num_phonemes=(3, 20)) + ' bandits')
        bandit_faction = Faction(leader_prefix='Bandit', name=bname, color=libtcod.black, succession='strongman', defaultly_hostile=1)

        # ## Choose building for site
        # if hideout_site is None:
        #     hideout_site = self.tiles[wx][wy].create_and_add_minor_site(world=self, type_='hideout', char='#', name=None, color=libtcod.black)
        #     hideout_building = hideout_site.create_building(zone='residential', type_='hideout', template='TEST', professions=[], inhabitants=[], tax_status=None)
        # else:
        #     hideout_building = random.choice(hideout_site.buildings)
        # ##########################
        # bandit_faction.set_headquarters(hideout_building)

        # Create a bandit leader from nearby city
        born = g.WORLD.time_cycle.years_ago(roll(18, 35))
        leader = closest_city.create_inhabitant(sex=1, born=born, dynasty=None, important=1, house=None)
        bandit_faction.add_member(leader)
        bandit_faction.set_leader(leader)

        # Set profession, weirdly enough
        profession = Profession(name='Bandit', category='bandit')
        profession.give_profession_to(figure=leader)
        # profession.set_building(building=hideout_building)

        # Give him the house
        # hideout_site.add_citizen(entity=leader, house=hideout_building)
        # Have him actually go there
        leader.w_teleport(wx, wy)

        sentients = {leader.creature.culture:{leader.creature.type_:{'Bandit':10}}}
        self.create_population(char='u', name='Bandit band', faction=bandit_faction, creatures={}, sentients=sentients, econ_inventory={'food':1}, wx=wx, wy=wy, site=hideout_site, commander=leader)

        building = leader.world_brain.choose_building_to_live_in()
        leader.world_brain.set_goal(goal_state=goap.HaveShelterInBuilding(entity=leader, building=building), reason='I need shelter!', priority=1)

        ## Prisoner
        #prisoner = closest_city.create_inhabitant(sex=1, born=WORLD.time_cycle.current_year-roll(18, 35), dynasty=None, important=0, house=None)
        #bandits.add_captive(figure=prisoner)
        ############

        return leader


    def create_population(self, char, name, faction, creatures, sentients, econ_inventory, wx, wy, site=None, commander=None):
        population = Population(char, name, faction, creatures, sentients, econ_inventory, wx, wy, site, commander)
        self.tiles[wx][wy].populations.append(population)
        self.tiles[wx][wy].chunk.add_population(population)

        return population


class DrunkWalker:
    def __init__(self, umap, x, y, cfg):
        self.umap = umap
        self.x = x
        self.y = y
        self.cfg = cfg

    def drunk_walk(self):
        x, y = self.x, self.y

        walked_tiles = []

        while 1:
            neighbors = get_border_tiles(x, y)

            # Chance of giving into the bias (if it exists), else, pick at random
            if self.cfg['bias'] and roll(1, 1000) < self.cfg['bias'][1]:
                xx, yy = neighbors[self.cfg['bias'][0]]
            else:
                xx, yy = random.choice(neighbors)
            # If the choice is valid, set the tile as unblocked
            if self.umap.is_val_xy((xx, yy)):
                # if blocked, unblock it
                if self.umap.tiles[xx][yy].blocks_mov and self.umap.tiles[xx][yy].height > g.WATER_HEIGHT:
                    self.umap.tiles[xx][yy].blocks_mov = 0
                    self.umap.tiles[xx][yy].blocks_vis = 0
                    self.umap.tiles[xx][yy].colorize(self.cfg['color'])
                    self.umap.tiles[xx][yy].surface = 'ground'

                    walked_tiles.append((xx, yy))

                # If config stops on first empty tile, this stops
                elif self.cfg['empty_stop'] and (not self.umap.tiles[xx][yy].blocks_mov) and (xx, yy) not in walked_tiles:
                    return walked_tiles
                # Refresh the x and y values
                x, y = xx, yy

            # Else handle tile limits
            if self.cfg['tile_limit'] > 0 and len(walked_tiles) >= self.cfg['tile_limit']:
                return walked_tiles


class Feature:
    def __init__(self, type_, x, y):
        self.type_ = type_
        self.x = x
        self.y = y
        self.name = None

    def set_name(self, name):
        self.name = name

    def get_name(self):
        if self.name:
            return self.name
        else:
            return self.type_

class River(Feature):
    def __init__(self, x, y):
        Feature.__init__(self, 'river', x, y)

        # Stores which directions the river is connected from
        self.connected_dirs = []

    def get_connected_dirs(self):
        return self.connected_dirs

    def add_connected_dir(self, direction):
        self.connected_dirs.append(direction)

class Site:
    def __init__(self, world, type_, x, y, char, name, color, underground=0):
        self.world = world
        self.type_ = type_
        self.x = x
        self.y = y
        self.underground = underground
        self.char = char
        self.name = name
        self.color = color

        self.leader = None

        # Set to the economy instance a site is attached to, if it has one
        self.econ = None

        self.departing_merchants = []
        self.goods = {}
        self.caravans = []

        # Structures
        self.buildings = []
        # Major figures who are citizens
        self.entities_living_here = []
        # Populations
        self.populations_living_here = []

        # Manage the world's dict of site types
        self.world.add_to_site_index(self)
        self.is_holy_site_to = []
        self.associated_events = set([])
        # For resources
        self.native_res = {}

        self.nearby_resources, self.nearby_resource_locations = self.world.find_nearby_resources(self.x, self.y, 6)


    # def get_leader_culture(self):
    #     ''' Return the culture of the leader of the site, if it has one'''
    #     return self.leader.creature.culture if self.leader else None

    def get_culture(self):
        ''' Return the culture of the leader of the site, if it has one'''
        return self.leader.creature.culture if self.leader else None

    def get_faction(self):
        ''' Return the faction of the leader of the site, if it has one'''
        return self.leader.creature.faction if self.leader else None

    def set_leader(self, entity):
        ''' Set leader of site - (sites don't need leaders though) '''
        self.leader = entity

    def get_building(self, building_name):
        ''' Find a specific building by name '''
        for building in self.buildings:
            if building.name == building_name:
                return building

    def get_building_type(self, building_type):
        ''' Find all buildings of a certain type '''
        return [building for building in self.buildings if building.type_ == building_type]

    def get_population(self):
        ''' Get total population at this site, both abstracted and generated '''

        ## TODO - ensure economy agents get added as part of the self.populations_living_here list
        population_from_econony = sum(agent.population_number for agent in self.econ.agents) if self.econ else 0

        return  population_from_econony + len(self.entities_living_here) + len(self.populations_living_here)

    def add_citizen(self, entity, house=None):
        ''' Handles removing person from their old site, and adding them to a new site '''

        # Make sure it's not duping anyone
        if entity in self.entities_living_here:
            return

        # Remove from old citizenship
        if entity.creature.current_citizenship:
            entity.creature.current_citizenship.remove_citizen(entity=entity)

        #### Make sure our new inhabitant has a house ####
        ## Check for spouse at site
        if house is None and entity.creature.spouse and entity.creature.spouse.creature.house and entity.creature.spouse.creature.house.site == self:
            house = entity.creature.spouse.creature.house
        ## Check for father at this site
        elif house is None and entity.creature.get_age() < g.MIN_CHILDBEARING_AGE and entity.creature.father and \
                entity.creature.father.creature.house and entity.creature.father.creature.house.site == self:
            house = entity.creature.father.creature.house
        ## Check for mother at this site
        elif house is None and entity.creature.get_age() < g.MIN_CHILDBEARING_AGE and entity.creature.mother and \
                entity.creature.father.creature.house and entity.creature.mother.creature.house.site == self:
            house = entity.creature.mother.creature.house
        else:
            house = self.create_building(zone='residential', type_='house', template='TEST', professions=[], inhabitants=[entity], tax_status='commoner')
            # print '{0}, age {1}, created a new house in {2}'.format(entity.fulltitle(), entity.creature.get_age(), self.get_name())

        # Add entity to house's inhabitants
        house.add_inhabitant(inhabitant=entity)

        # Swap current citizenship, add to list of citizens
        entity.creature.current_citizenship = self
        self.entities_living_here.append(entity)

        if self.get_faction():
            # Remove old faction stuff
            if entity.creature.faction:
                entity.creature.faction.remove_member(entity)
            # Add to this faction -- needed???
            self.get_faction().add_member(entity)


    def remove_citizen(self, entity):
        ''' Remove associations from an entity to a site '''
        self.entities_living_here.remove(entity)
        entity.creature.current_citizenship = None

        # Remove old housing stuff
        if entity.creature.house:
            assert entity.creature.house.site == self, 'Citizen of {0}\'s house\'s was at a different site than their citizenship'
            entity.creature.house.remove_inhabitant(entity)


    def create_building(self, zone, type_, template, professions, inhabitants, tax_status):
        building = building_info.Building(zone=zone, type_=type_, template=template, site=self, construction_material='stone cons materials', professions=professions, inhabitants=inhabitants, tax_status=tax_status, wx=self.x, wy=self.y)
        self.buildings.append(building)
        return building

    def finish_constructing_building(self, building):
        ''' Used when adding a building which has already been created programmatically '''
        building.constructed = 1
        self.buildings.append(building)
        return building

    def get_name(self):
        if self.name:
            return self.name
        else:
            return indef(self.type_)

    def create_inhabitant(self, sex, born, dynasty, important, race=None, armed=0, house=None, char=None, world_char=None):
        ''' Add an inhabitant to the site '''

        # First things first - if this happens to be a weird site without a culture, inherit the closest city's culture (and pretend it's our home_site)
        if self.get_culture() is None:
            city = g.WORLD.get_closest_city(x=self.x, y=self.y, max_range=1000)[0]
            culture = city.get_culture()
            home_site = city
        else:
            culture = self.get_culture()
            home_site = self

        human = culture.create_being(sex=sex, born=born, dynasty=dynasty, important=important, faction=self.get_faction(),
                                     wx=self.x, wy=self.y, armed=armed, race=race, save_being=1, char=char, world_char=world_char)

        human.creature.home_site = home_site
        self.add_citizen(human)

        return human

    def run_random_encounter(self):
        # Random chance of 2 people encountering each other in a city.
        if len(g.WORLD.tiles[self.x][self.y].entities) > 2:
            entity1 = random.choice(g.WORLD.tiles[self.x][self.y].entities)
            entity2 = random.choice(g.WORLD.tiles[self.x][self.y].entities)
            if entity1 != entity2:
                entity1.creature.encounter(other=entity2)
                entity2.creature.encounter(other=entity1)
                # g.game.add_message(' -*- {0} encounters {1} in {2} -*-'.format(entity1.fulltitle(), entity2.fulltitle(), self.get_name()), libtcod.color_lerp(g.PANEL_FRONT, self.color, .3))

    def distance_to(self, other):
        #return the distance to another object
        dx = other.x - self.x
        dy = other.y - self.y
        return math.sqrt(dx ** 2 + dy ** 2)

    def distance(self, x, y):
        #return the distance to some coordinates
        return math.sqrt((x - self.x) ** 2 + (y - self.y) ** 2)

    def w_draw(self):
        #only show if it's visible to the g.player
        #if libtcod.map_is_in_fov(fov_map, self.x, self.y):
        (x, y) = g.game.camera.map2cam(self.x, self.y)

        if x is not None:
            #set the color and then draw the character that represents this object at its position
            libtcod.console_set_default_foreground(g.game.interface.map_console.con, self.color)
            #libtcod.console_set_default_background(con.con, self.color)

            libtcod.console_put_char(g.game.interface.map_console.con, x, y, self.char, libtcod.BKGND_NONE)
            # 2nd half of the tile
            libtcod.console_put_char(g.game.interface.map_console.con, x+1, y, self.char+1, libtcod.BKGND_NONE)


    def clear(self):
        #erase the character that represents this object
        (x, y) = g.game.camera.map2cam(self.x, self.y)
        if x is not None:
            libtcod.console_put_char(g.game.interface.map_console.con, x, y, ' ', libtcod.BKGND_NONE)


class City(Site):
    def __init__(self, world, type_, x, y, char, name, color):
        ## Initialize site ##
        Site.__init__(self, world, type_, x, y, char, name, color)

        self.connected_to = []
        self.path_to = {}

        self.war = []
        self.former_agents = []
        self.treasury = 500

        # Start with radius 3, gets immediately expanded to 4
        self.territory = []
        self.old_territory = [] # formerly owned tiles added here
        self.territory_radius = 1

        self.imports = defaultdict(list)
        self.exports = defaultdict(list)

        # Below are set up in prepare_native_economy(), as well as self.econ
        self.resource_slots = {}
        self.industry_slots = {}

        # self.building_construction_queue =
        # Maps objects (keys) to a list of agents
        # Eg. 'sword':['Bronze Weaponsmith', 'Copper Weaponsmith']
        self.object_to_agents_dict = defaultdict(list)

        # Add resources to the city, for the purposes of the economy
        for resource, amount in g.WORLD.tiles[self.x][self.y].res.iteritems():
            self.obtain_resource(resource, amount - 10)

        self.acquire_tile(self.x, self.y)
        self.increase_radius(amount=2)
        ## A package of buildings to start with
        # self.setup_initial_buildings()


    def update_object_to_agents_dict(self):
        ''' This dict helps us find which objects can be bought at which cities. This will may be somewhat out-of-sync
            with the actual possibilities, due to new agents being added or old ones being removed. However, it should
            be close enough to work most of the time, assuming entity AI should takes this into account. '''

        # Reset this attribute
        self.object_to_agents_dict = defaultdict(list)

        already_checked = []
        for agent in [a for a in self.econ.agents if a.reaction.is_finished_good]:
            if agent.name in already_checked:
                continue

            # Loop through all objects produced by the agent and add them as keys; append the agent name into the values
            for object_name in agent.get_sold_objects():
                self.object_to_agents_dict[object_name].append(agent.name)

            already_checked.append(agent.name)

    def connect_to(self, other_city):
        self.connected_to.append(other_city)
        other_city.connected_to.append(self)

    def add_import(self, city, good):
        # Add other city as an importer if it's not already
        self.imports[city].append(good)

    def add_export(self, city, good):
        # Add other city as an exporter if it's not already
        self.exports[city].append(good)

    def remove_import(self, city, good):
        # Remove the import
        self.imports[city].remove(good)
        # And if we no longer import antything from them, remove from dict
        if self.imports[city] == []:
            del self.imports[city]

    def remove_export(self, city, good):
        # Remove the export
        self.exports[city].remove(good)
        # And if we no longer export antything to them, remove from dict
        if self.exports[city] == []:
            del self.exports[city]

    def get_all_imports(self):
        return [item for sublist in self.imports.values() for item in sublist]

    def get_all_exports(self):
        return [item for sublist in self.exports.values() for item in sublist]

    def prepare_native_economy(self):
        # Add economy to city
        self.econ = economy.Economy(native_resources=self.native_res.keys(), local_taxes=g.DEFAULT_TAX_AMOUNT, owner=self)

        for resource_type, amount in data.CITY_RESOURCE_SLOTS.iteritems():
            for resource_class in data.commodity_manager.get_commodities_of_type(resource_type):
                if resource_class.name in self.native_res:
                    self.resource_slots[resource_class.name] = amount

        good_tokens_we_can_produce = economy.list_goods_from_strategic(self.native_res.keys())
        for good_type, amount in data.CITY_INDUSTRY_SLOTS.iteritems():
            for good_class in data.commodity_manager.get_commodities_of_type(good_type):
                if good_class.name in good_tokens_we_can_produce:
                    self.industry_slots[good_class.name] = amount


    def setup_native_economy(self):
        # Add gatherers and producers based on the slots allocated when we prepared the economy
        for resource, amount in self.resource_slots.iteritems():
            for i in xrange(amount):
                self.econ.add_agent_based_on_token(resource)

        for good, amount in self.industry_slots.iteritems():
            for i in xrange(amount):
                self.econ.add_agent_based_on_token(good)

    def setup_imports(self):


        goods_by_resource_token = data.commodity_manager.get_goods_by_resource_token()

        for city, import_list in self.imports.iteritems():
            for commodity in import_list:

                # Make sure to add it to the economy's import tax rates
                if commodity not in self.econ.imported_commodity_tax_rates:
                    self.econ.imported_commodity_tax_rates[commodity] = economy.DEFAULT_IMPORT_TAX_RATE

                ## It's coming up with good in the import list...
                if commodity in goods_by_resource_token:
                    ## Add merchants to the other city, who sell stuff in this city
                    city.create_merchant(sell_economy=self.econ, sold_commodity_name=commodity)
                    city.create_merchant(sell_economy=self.econ, sold_commodity_name=commodity)
                    ## Add extra resource gatherers in the other city
                    #city.econ.add_agent_based_on_token(item)

                    ## Add some specialists who can now make use of the imported goods
                    good_tokens_this_resource_can_produce = economy.list_goods_from_strategic([commodity])
                    for good in good_tokens_this_resource_can_produce:
                        self.econ.add_agent_based_on_token(good)
                        # self.econ.add_agent_based_on_token(good)

                        # Other city too!
                        city.econ.add_agent_based_on_token(good)
                        city.econ.add_agent_based_on_token(good)
                        city.econ.add_agent_based_on_token(good)
                        # city.econ.add_agent_based_on_token(good)

                    ## Add some merchants who will sell whatever good is created from those resources
                    for good_class in goods_by_resource_token[commodity]:
                        city.create_merchant(sell_economy=self.econ, sold_commodity_name=good_class.name)
                        city.create_merchant(sell_economy=self.econ, sold_commodity_name=good_class.name)

                        #city.create_merchant(sell_economy=self.econ, traded_item=good_class.name)
                        #city.create_merchant(sell_economy=self.econ, traded_item=good_class.name)
                        self.add_import(city, good_class.name)
                        city.add_export(self, good_class.name)


    def build_road_to(self, x, y, color=libtcod.darkest_sepia):
        road_path = libtcod.path_compute(g.WORLD.rook_path_map, self.x, self.y, x, y)

        x, y = self.x, self.y
        old_x, old_y = None, None
        while x is not None:
            # Update the road path map to include this road
            libtcod.map_set_properties(g.WORLD.road_fov_map, x, y, 1, 1)

            if old_x:
                g.WORLD.make_world_road(old_x, old_y)

            old_x, old_y = x, y
            x, y = libtcod.path_walk(g.WORLD.rook_path_map, True)

    def create_merchant(self, sell_economy, sold_commodity_name):
        ## Create a human to attach an economic agent to
        born = g.WORLD.time_cycle.years_ago(roll(20, 60))
        human = self.create_inhabitant(sex=1, born=born, dynasty=None, important=0, house=None, world_char=g.MERCHANT_TILE)
        human.set_world_brain(BasicWorldBrain())

        ## Actually give profession to the person ##
        market = self.get_building('Market')
        market.add_profession(Profession(name='{0} Merchant'.format(sold_commodity_name), category='merchant'))
        market.professions[-1].give_profession_to(human)

        merchant = self.econ.add_merchant(sell_economy=sell_economy, sold_commodity_name=sold_commodity_name, attached_to=human)
        location = merchant.current_location.owner

        # A bit of a hack to make sure the merchant starts in the appropriate city
        if location != self:
            # Send him off
            market.remove_worker(human)
            # Teleport the merchant to the other location
            human.w_teleport(location.x, location.y)
            location.get_building('Market').add_worker(human)

        ## Now add the caravan to a list
        sentients = {self.get_culture():{random.choice(self.get_culture().races):{'Caravan Guard':roll(10, 20)}}}
        g.WORLD.create_population(char='M', name='{0} caravan'.format(self.name), faction=self.get_faction(), creatures={}, sentients=sentients, econ_inventory={}, wx=location.x, wy=location.y, commander=human)

        #location.caravans.append(human)

    def dispatch_caravans(self):
        market = self.get_building('Market')

        for caravan_leader, destination in self.departing_merchants:
            for figure in caravan_leader.creature.commanded_figures:
                if figure in market.current_workers:
                    market.remove_worker(figure)
                else:
                    g.game.add_message('{0} tried to dispatch with the caravan but was not in {1}\'s list of figures'.format(figure.fulltitle(), self.name), g.DEBUG_MSG_COLOR)

            # Remove from city's list of caravans
            if caravan_leader in self.caravans:
                self.caravans.remove(caravan_leader)

            # caravan_leader.world_brain.next_tick = g.WORLD.time_cycle.next_day()
            # Tell the ai where to go
            commodities = caravan_leader.creature.economy_agent.merchant_travel_inventory
            if destination.econ == caravan_leader.creature.economy_agent.sell_economy:
                caravan_leader.world_brain.set_goal(goal_state=goap.CommoditiesAreUnloaded(target_city=destination, commodities=commodities, entity=caravan_leader), reason='I need to make a living you know')
            elif destination.econ == caravan_leader.creature.economy_agent.buy_economy:
                caravan_leader.world_brain.set_goal(goal_state=goap.CommoditiesAreLoaded(target_city=destination, commodities=commodities, entity=caravan_leader), reason='I need to make a living you know')

        self.departing_merchants = []

    def receive_caravan(self, caravan_leader):
        market = self.get_building('Market')

        # Unload the goods
        if self.econ == caravan_leader.creature.economy_agent.sell_economy:
            caravan_leader.creature.economy_agent.unload_goods(caravan_leader.creature.economy_agent.sell_economy)

        # Add workers to the market
        for figure in caravan_leader.creature.commanded_figures + [caravan_leader]:
            if figure.creature.economy_agent:
                figure.creature.economy_agent.current_location = self.econ
                market.add_worker(figure)

        #g.WORLD.tiles[caravan_leader.wx][caravan_leader.wy].entities.remove(caravan_leader)
        self.caravans.append(caravan_leader)

    def increase_radius(self, amount=1):
        ''' Increase the territory held by the city '''
        self.territory_radius += amount
        # It is important to make sure the tiles in the circle have been sorted first, so that is_valid_territory_to_acquire doesn't get a disconnected tile
        for x, y in get_sorted_circle_tiles(self.x, self.y, self.territory_radius):
            if g.WORLD.tiles[x][y].territory != self and self.is_valid_territory_to_acquire(x, y) and not g.WORLD.tiles[x][y].blocks_mov \
                    and (g.WORLD.tiles[x][y].territory is None or self.is_valid_to_steal_from_other_city(x, y)):
                self.acquire_tile(x, y)

    def is_valid_territory_to_acquire(self, x, y):
        ''' Only is valid territory if it borders at least one existing tile '''
        return any([g.WORLD.tiles[xx][yy].territory == self for xx, yy in get_border_tiles(x, y)]) or g.WORLD.tiles[x][y].site == self

    def is_valid_to_steal_from_other_city(self, x, y):
        ''' If it's a closeby territory, even if another city owns it, if it's closer to use, we can acquire it '''
        return g.WORLD.tiles[x][y].territory and g.WORLD.tiles[x][y].territory != self and self.distance(x, y) < g.WORLD.tiles[x][y].territory.distance(x, y)

    def obtain_resource(self, resource, amount):
        if resource not in self.native_res:
            self.native_res[resource] = amount

    def acquire_tile(self, x, y):
        # acquire a single tile for the city
        if g.WORLD.tiles[x][y].culture is None:
            g.WORLD.tiles[x][y].culture = self.get_culture()

        if g.WORLD.tiles[x][y].territory is not None:
            # If owned, add to civ/city's memory of territory, and remove from actual territory
            oldcity = g.WORLD.tiles[x][y].territory

            oldcity.old_territory.append(g.WORLD.tiles[x][y])
            oldcity.territory.remove(g.WORLD.tiles[x][y])

        g.WORLD.tiles[x][y].territory = self
        if (x, y) not in self.territory:
            self.territory.append(g.WORLD.tiles[x][y])

        # Add any resources
        for resource, amount in g.WORLD.tiles[x][y].res.iteritems():
            self.obtain_resource(resource=resource, amount=amount)

    def setup_initial_buildings(self):
        """Start the city off with some initial buildings"""
        city_hall_professions = [Profession(name='Scribe', category='commoner'),
                                 Profession(name='Scribe', category='commoner'),
                                 Profession(name='General', category='noble'),
                                 Profession(name='Tax Collector', category='commoner'),
                                 Profession(name='Spymaster', category='commoner'),
                                 Profession(name='Vizier', category='noble'),
                                 Profession(name='Militia Captain', category='commoner')]
        self.create_building(zone='municipal', type_='City Hall', template='TEST', professions=city_hall_professions, inhabitants=[], tax_status='noble')

        temple_professions = [Profession(name='High Priest', category='religion')]
        self.create_building(zone='municipal', type_='Temple', template='TEST', professions=temple_professions, inhabitants=[], tax_status='religious')

        market_professions = []
        self.create_building(zone='market', type_='Market', template='TEST', professions=market_professions, inhabitants=[], tax_status='general')

        # Some nobles and estates
        #for i in xrange(roll(2, 4)):
        #    estate_professions = [Profession(name='Noble', category='noble')]
        #    self.create_building(name='Estate', professions=estate_professions, tax_status='noble')

        for i in xrange(roll(4, 6)):
            tavern_professions = [Profession(name='Tavern Keeper', category='commoner'),
                                  Profession(name='Bard', category='commoner')]
            #if roll(0, 1):
            #    tavern_professions.append(Profession(name='Assassin', category='commoner'))

            self.create_building(zone='commercial', type_='Tavern', template='TEST', professions=tavern_professions, inhabitants=[], tax_status='commoner')

        ######### Fill positions #########
        for building in self.buildings:
            building.fill_initial_positions()


    def get_available_materials(self):
        ''' Return a raw resources that this city has access to'''
        return list({material for material in itertools.chain(self.native_res, self.get_all_imports()) if material in data.commodity_manager.resource_names})


class Profession:
    '''A profession for historical figures to have'''
    def __init__(self, name, category):
        self.name = name
        self.category = category

        self.holder = None
        self.building = None
        # This was mostly created due to merchants, who can be at work on one of two markets
        # This means the self.building is not sufficient. Might be able to drop self.building entirely?
        self.current_work_building = None

    def set_building(self, building):
        self.building = building
        self.current_work_building = building

    def set_current_work_building(self, building):
        self.current_work_building = building

    def give_profession_to(self, figure):
        # Remove current holder from buildings, and the profession
        if self.holder:
            if self.building:   location = ' in {0}'.format(self.building.site.name)
            else:               location = ''

            g.game.add_message('{0} has replaced {1} as {2}{3}'.format(figure.fullname(), self.holder.fullname(), self.name, location), libtcod.light_green)
            if self.current_work_building:
                self.current_work_building.remove_worker(self.holder)
            self.holder.creature.profession.remove_profession_from(self.holder)

        figure.creature.profession = self
        # Update infamy, if necessary
        if self.name in g.PROFESSION_INFAMY:
            figure.add_infamy(amount=g.PROFESSION_INFAMY[self.name])
        ## Quick fix for merchants all having unique names
        elif self.category in g.PROFESSION_INFAMY:
            figure.add_infamy(amount=g.PROFESSION_INFAMY[self.category])
        #else:
        #    print '{0} not part of PROFESSION_INFAMY'.format(self.name)

        # Put as a placeholder until we track satasfying the requirements beforehand
        if self.name in g.LITERATE_PROFESSIONS  or self.category in g.LITERATE_PROFESSIONS:
            figure.creature.update_language_knowledge(language=g.WORLD.lingua_franca, written=10)


        self.holder = figure
        # Has to be done afterward, so the profession's current building can be set
        if self.current_work_building:
            self.current_work_building.add_worker(figure)

        figure.creature.set_opinions()

    def remove_profession_from(self, figure):
        figure.creature.profession = None
        self.holder = None
        figure.creature.set_opinions()

class Faction:
    def __init__(self, leader_prefix, name, color, succession, defaultly_hostile=0):
        # What the person will be referred to as, "Mayor" "governor" etc (None for no leader
        self.leader_prefix = leader_prefix
        self.name = name
        self.color = color

        self.leader = None
        self.site = None
        # Eventually will be more precide? Just a way to keep track of when the current leader became leader
        self.leader_change_year = g.WORLD.time_cycle.current_year
        # So far:
        # 'dynasty' for a city type faction
        # 'strongman' for bandit factions
        self.succession = succession
        self.heirs = []

        # Controls whether we're hostile by default (e.g. bandit gangs)
        self.defaultly_hostile = defaultly_hostile

        self.headquarters = None

        g.WORLD.factions.append(self)

        # Information about ranking
        self.parent = None
        self.subfactions = []
        self.members = []

        self.weapons = []

        # All objects unique to the faction
        self.unique_object_dict = {}

        self.faction_relations = {}
        # Factions whom we would openly fight
        self.enemy_factions = set([])

        # Only used for defaultly hostiles - Factions who we would not openly fight
        self.friendly_factions = set([])


    def is_hostile_to(self, faction):
        ''' Figure out whether we are hostile to another faction '''
        return (faction != self) and ( (faction in self.enemy_factions) or (self.defaultly_hostile and not faction in self.friendly_factions) or (faction.defaultly_hostile and not faction in self.friendly_factions) )


    def set_friendly_faction(self, faction):
        if self.defaultly_hostile:
            self.friendly_factions.add(faction)

        if faction.defaultly_hostile:
            faction.friendly_factions.add(self)

    def unset_friendly_faction(self, faction):
        if self.defaultly_hostile:
            self.friendly_factions.remove(faction)
        if faction.defaultly_hostile:
            faction.friendly_factions.remove(self)


    def set_enemy_faction(self, faction):
        self.enemy_factions.add(faction)
        faction.enemy_factions.add(self)

    def unset_enemy_faction(self, faction):
        self.ememy_factions.remove(faction)
        faction.enemy_factions.remove(self)


    def set_headquarters(self, building):
        self.headquarters = building
        self.headquarters.faction = self

    def set_site(self, site):
        self.site = site

    def add_member(self, figure):
        figure.creature.faction = self
        figure.set_color(self.color)

        self.members.append(figure)

    def remove_member(self, figure):
        #figure.creature.faction = None
        self.members.remove(figure)

    def set_leader(self, leader):
        # Now install new leader
        self.leader = leader
        # Keep track of when leader became leader
        self.leader_change_year = g.WORLD.time_cycle.current_year

    def get_leader(self):
        return self.leader


    def modify_faction_relations(self, faction, reason, amount):
        if faction in self.faction_relations:
            if reason in self.faction_relations[faction]:
                self.faction_relations[faction][reason] += amount

            elif reason not in self.faction_relations[faction]:
                self.faction_relations[faction][reason] = amount

        elif faction not in self.faction_relations:
            self.faction_relations[faction] = {reason:amount}

    def get_faction_relations(self, other_faction):

        reasons = {}

        if other_faction in self.faction_relations:
            for reason, amount in self.faction_relations[other_faction]:
                reasons[reason] = amount

        # Culture
        if other_faction.get_leader() and self.get_leader() and other_faction.get_leader().creature.culture != self.get_leader().creature.culture:
            reasons['Different culture'] = -10

        if other_faction in self.subfactions or self in other_faction.subfactions:
            reasons['Same political entity'] = 10

        return reasons

    def set_subfaction(self, other_faction):
        # Adds another title as vassal
        other_faction.parent = self
        self.subfactions.append(other_faction)



    def standard_succession(self):
        ''' Leadership will pass to the firstborn son of the current holder.
        If none, it will pass to the oldest member of the dynasty'''
        if self.heirs != []:
            heir = self.heirs.pop(0)
            # Now that they're in the new position, remove them from the list of heirs
            self.unset_heir(heir)
            self.set_leader(heir)
            g.game.add_message('{0} has is now {1} of {2}'.format(heir.fullname(), self.leader_prefix, self.name))
            # Re-calculate succession
            self.get_heirs(3)

        # Not sure if title should immediately pass onto someone, or have None be a valid holder for the title
        # while others fight it out.
        else:
            g.game.add_message('{0} now has no heir!'.format(self.name))


    def set_heir(self, heir, number_in_line):
        self.heirs.append(heir)
        heir.creature.inheritance[self] = number_in_line

    def unset_heir(self, heir):
        assert self in heir.creature.inheritance, '%s not in %s\'s inheritance' %(self.name, heir.fulltitle())
        del heir.creature.inheritance[self]

    def get_heirs(self, number):
        # First, make sure to clear the knowledge of inheritance from all heirs
        if self.leader_prefix is not None:
            # TODO - this is causing dict to change size during iteration on death, because it is removing the dead entity from the list
            # Must rewrite to take this into account
            #for heir in self.heirs:
            #          self.unset_heir(heir)

            if self.leader and self.succession == 'dynasty':
                self.heirs = []

                child_heirs = [child for child in self.leader.creature.children if child.creature.sex == 1 and not child.creature.status == 'dead']
                child_heirs = sorted(child_heirs, key=lambda child: child.creature.born)
                ## Look at other heirs - make sure it does not include the title holder himself or his children, since they're already accounted for
                if self.leader.creature.dynasty is not None:
                    other_heirs = [member for member in self.leader.creature.dynasty.members if member.creature.sex == 1 and member != self.leader and member not in child_heirs and not member.creature.status == 'dead']
                    other_heirs = sorted(other_heirs, key=lambda member: member.creature.born)

                else:
                    logging.warning('BUG: {0} has no dynasty'.format(self.leader.fullname()) )
                    other_heirs = []
                # Child heirs will be given priority
                merged_list = child_heirs + other_heirs

                for i, heir in enumerate(merged_list[:number]):
                    self.set_heir(heir=heir, number_in_line=i+1)

                return merged_list[:number]


            elif self.leader and self.succession == 'strongman':
                self.heirs = []

                heir = random.choice(self.members)
                if heir is None:
                    born = g.WORLD.time_cycle.years_ago(roll(20, 45))
                    heir = self.headquarters.site.get_culture().create_being(sex=1, born=born, dynasty=None, important=0, faction=self, wx=self.headquarters.site.x, wy=self.headquarters.site.y, armed=1, save_being=1)
                    self.set_heir(heir=heir, number_in_line=1)

                return [heir]

            else:
                logging.warning('{0} was queried for heirs but has no holder'.format(self.name))
                return []

    def create_faction_objects(self):
        ''' Culturally specific weapons '''

        # Go through all objects in the master dictionary and duplicate the common-pool ones
        for obj in phys.object_dict:
            if phys.object_dict[obj]['availability'] == 'common':
                self.unique_object_dict[obj] = phys.object_dict[obj]


        weapon_types = phys.blueprint_dict.keys()
        #materials = self.site.get_available_materials()
        ## TODO - check union of weapon materials/available materials
        materials = ('iron', 'copper', 'bronze')

        ''' Create a few types of unique weapons for this culture '''
        for wtype in weapon_types:
            material_name = random.choice(materials)
            material = data.commodity_manager.materials[material_name]

            special_properties = {random.choice(phys.PROPERTIES): random.choice( (5, 10) ) }

            # Send it over to the item generator to generate the weapon
            weapon_info_dict = phys.wgenerator.generate_weapon(wtype=wtype, material=material, special_properties=special_properties)

            # Pick weapon name, either by culture of leader or culture of site
            if self.leader:
                weapon_name = self.leader.creature.culture.gen_word(syllables=roll(1, 2), num_phonemes=(2, 8))
            else:
                weapon_name = self.site.get_culture().gen_word(syllables=roll(1, 2), num_phonemes=(2, 8))

            name = '{0} {1}'.format(weapon_name, wtype)
            weapon_info_dict['name'] = name

            # Finally, append to list of object dicts
            self.weapons.append(name)

            phys.object_dict[name] = weapon_info_dict

            # Add to our own set of unique items
            self.unique_object_dict[name] = weapon_info_dict


## The object itself is basically a list of components
class Object:
    def __init__(self, name, char, color, components, blocks_mov, blocks_vis, description,
                 creature=None, local_brain=None, world_brain=None,
                 weapon=None, wearable=None,
                 x=None, y=None, wx=None, wy=None, world_char=None):

        self.name = name
        self.char = char
        self.world_char = char if not world_char else world_char

        self.set_color(color)

        ## (Physical) components of the object; and then run a routine to put them all together
        self.components = components
        self.set_initial_attachments()
        # blocks = block pathing, blocks_vis = blocks vision
        self.blocks_mov = blocks_mov
        self.blocks_vis = blocks_vis

        self.description = description

        self.creature = creature
        if self.creature:  #let the creature component know who owns it
            self.creature.owner = self

        # For the local map
        self.set_local_brain(local_brain)
        # For the world map
        self.set_world_brain(world_brain)

        # If this thing was designed as a weapon, this flag keeps track of it
        self.weapon = weapon

        # All tags associated with components which make up this object
        self.tags = self.get_tags()
        # Tag that would mark this item as an economy item
        self.econ_tag = None

        # How important / well-known this object is - also tracks entities' importance level
        self.infamy = 0

        self.wearing = []
        self.wearable = wearable
        self.being_worn = 0

        # x and y coords in battle-map game world
        self.x = x
        self.y = y
        # x and y coords in overworld map
        self.wx = wx
        self.wy = wy
        self.world_last_dir = (0, 0)
        self.turns_since_move = 0
        self.associated_events = set([])

        # Will be set to an interact_obj class instance if used
        self.interactable = 0

        #self.momentum = 0
        #self.height = 1.6

        # The being that owns the object - will probably be the last to touch it?
        self.current_owner = None
        # Building that the object is currently in
        self.current_building = None
        # If the object is currently on someone's person
        self.current_holder = None


        self.inside = None  # Keeps track of objects we're inside of
        self.being_grasped_by = None # body part grasping it


        self.cached_astar_path = None

    def get_tags(self):
        ''' Return set of all tags which our components are tagged with '''
        tags = set([])
        for component in self.components:
            for tag in component.tags:
                tags.add(tag)

        return tags

    def set_local_brain(self, brain):
        self.local_brain = brain
        if self.local_brain:  #let the AI component know who owns it
            self.local_brain.owner = self

    def set_world_brain(self, brain):
        self.world_brain = brain
        if self.world_brain:  #let the AI component know who owns it
            self.world_brain.owner = self


    def set_color(self, color):
        self.color = color
        # Color which gets displayed:
        self.display_color = color
        self.shadow_color = self.color * .5
        # Set special colors for different states of the object
        self.pass_out_color = libtcod.color_lerp(self.color, libtcod.black, .5)
        self.death_color = libtcod.black


    def add_associated_event(self, event_id):
        self.associated_events.add(event_id)

        # Update knowledge
        if self.creature:
            self.creature.add_knowledge_of_event(event_id=event_id, date_learned=g.WORLD.time_cycle.get_current_date(), source=self)
            self.creature.add_knowledge_of_event_location(event_id=event_id, date_learned=g.WORLD.time_cycle.get_current_date(), source=self, location_accuracy=5)

    def add_infamy(self, amount):
        self.infamy += amount

    def read_information(self, entity=None):

        date = g.WORLD.time_cycle.get_current_date()
        if entity is None:
            entity = g.player

        # Loop through all components, and then all languages in components, and then all messages in that language
        for component in self.components:
            for language in component.information:
                can_glean_some_information = 0
                g.game.add_message('The {0} contains information written in {1}'.format(component.name, language.name))

                # Check whether this is readable
                if entity.creature.can_read(language):
                    can_glean_some_information = 1
                    g.game.add_message('You can read this.')

                    for event_id in component.information[language]['events']:
                        g.game.add_message(hist.historical_events[event_id].describe())

                        location_accuracy = component.information[language]['events'][event_id]['location']['accuracy']
                        entity.creature.add_knowledge_of_event(event_id=event_id, date_learned=date, source=self, location_accuracy=location_accuracy)

                    for site in component.information[language]['sites']:
                        # This is for site information that is not part of a map, since that's something we need to read
                        if not component.information[language]['sites'][site]['location']['is_part_of_map']:
                            g.game.add_message('Adding knowledge of {0}'.format(site.get_name()))

                            location_accuracy = component.information[language]['sites'][site]['location']['accuracy']
                            entity.creature.add_knowledge_of_site(site=site, date_learned=date, source=self, location_accuracy=location_accuracy)

                # End language check - below info is readable anyway
                # Loop to figure out if there's any map infor (don't need language to read a map)
                map_info = 0
                site_info = {'readable':{
                                    'named': {'known':[], 'unknown':[] },
                                    'unnamed': {'known':[], 'unknown':[] },
                                    },
                             'unreadable':{
                                    'named': {'known':[], 'unknown':[] },
                                    'unnamed': {'known':[], 'unknown':[] }
                                    }
                            }

                for site in component.information[language]['sites']:
                    if component.information[language]['sites'][site]['location']['is_part_of_map']:
                        can_glean_some_information = 1
                        map_info = 1
                        # If you can read about the site
                        if entity.creature.can_read(language):
                            if site.name and site in entity.creature.knowledge['sites']:
                                site_info['readable']['named']['known'].append(site)
                            elif site.name and site not in entity.creature.knowledge['sites']:
                                site_info['readable']['named']['known'].append(site)
                            elif site.name is None and site in entity.creature.knowledge['sites']:
                                site_info['readable']['unnamed']['known'].append(site)
                            elif site.name is None and site not in entity.creature.knowledge['sites']:
                                site_info['readable']['unnamed']['unknown'].append(site)

                        ## You can read, but are not familiar
                        elif not entity.creature.can_read(language):
                            if site.name and site in entity.creature.knowledge['sites']:
                                site_info['unreadable']['named']['known'].append(site)
                            elif site.name and site not in entity.creature.knowledge['sites']:
                                site_info['unreadable']['named']['unknown'].append(site)
                            elif site.name is None and site in entity.creature.knowledge['sites']:
                                site_info['unreadable']['unnamed']['known'].append(site)
                            elif site.name is None and site not in entity.creature.knowledge['sites']:
                                site_info['unreadable']['unnamed']['unknown'].append(site)

                        location_accuracy = component.information[language]['sites'][site]['location']['accuracy']
                        entity.creature.add_knowledge_of_site(site=site, date_learned=date, source=self, location_accuracy=location_accuracy)

                # There is information there, that is not part of a map, and you can't read it
                if not can_glean_some_information:
                    g.game.add_message('The {0} text on the {1} is entirely indecipherable to you'.format(language.name, component.name), libtcod.red)

                if map_info:
                    # Condense the site descriptions into some readable text
                    msg = describe_map_contents(site_info)
                    g.game.add_message(msg, g.PANEL_FRONT)

    def set_current_owner(self, figure, traded=0):
        ''' Sets someone as the owner of an object (must run set_current_holder to make sure they're carrying it)'''
        ## Remove from current owner
        if self.current_owner:
            self.current_owner.creature.possessions.remove(self)
            # Only add to former possessions if not traded
            if not traded:
                self.current_owner.creature.former_possessions.add(self)

            #g.game.add_message('%s has taken possession of %s from %s' %(figure.fullname(), self.fullname(), self.current_owner.fullname()), libtcod.orange)
        else:
            pass
            #g.game.add_message('%s has taken possession of %s' %(figure.fullname(), self.fullname()), libtcod.orange)

        ## Give to new owner
        self.current_owner = figure
        figure.creature.possessions.add(self)


    def clear_current_owner(self):
        self.current_owner.creature.possessions.remove(self)
        self.current_owner.creature.former_possessions.add(self)

        self.current_owner = None

    def make_trade(self, other, my_trade_items, other_trade_items, price):
        ''' Exchange a set of items with another entity, and money as well '''
        other.add_items_to_inventory(items=my_trade_items)
        self.add_items_to_inventory(items=other_trade_items)

        self.creature.net_money -= price
        other.creature.net_money += price


    def add_items_to_inventory(self, items):
        ''' Adds a list of items into inventory, grasping them or storing them if necessary '''
        for i, item in enumerate(items):
            item.set_current_owner(figure=self, traded=1)
            own_component = [grasper for grasper in self.creature.get_graspers() if not grasper.grasped_item][0]
            self.pick_up_object(own_component=own_component, obj=item)

            # Store item if necessary
            if i != len(items) - 1:
                components_with_storage = self.get_storage_items()

                for component_with_storage in components_with_storage:
                    stored = component_with_storage.owner.place_inside(own_component=component_with_storage, other_object=item, grasping_component=own_component)
                    if stored:
                        break
                else:
                    g.game.add_message('{0} could not store {1}'.format(self.fullname(), item.fullname()), libtcod.red)



    def set_current_building(self, building):
        ''' Moves it to a building, but preserves the owner '''
        self.current_holder = None
        self.current_building = building

        building.add_housed_object(obj=self)
        self.wx, self.wy = building.site.x, building.site.y

    def set_current_holder(self, figure):
        ''' Moves it from a building to a person, preserving the owner '''
        if self.current_building:
            self.current_building.remove_housed_object(obj=self)
            self.current_building = None

        self.current_holder = figure

    def clear_current_holder(self):
        ''' Clears from current holder '''
        self.current_holder = None


    def clear_current_building_and_location(self):
        self.current_building.remove_housed_object(obj=self)
        self.current_building = None

    def set_initial_attachments(self):
        ''' Once the object is created, handle stuff which should be attached to each other.
        The first component should always be the "center" to which other things should be attached
        (and thus have no attachment info). Every other component should have a tuple containing
        attachment info. Unfortunately we have to store the string of the name of the component that
        it should be attaching to, since we won't have the actual component object created at the time
        that the component list is populated '''
        for component in self.components:
            # Make sure the component knows what object it belongs to!
            component.owner = self
            # Handle attachments
            if component.attachment_info != (None, None):
                name_of_target_component, attach_strength = component.attachment_info
                target_component = self.get_component_by_name(component_name=name_of_target_component)

                component.attach_to(target_component, attach_strength)

    def set_display_color(self, color):
        self.display_color = color


    def remove_from_map(self):
        ''' For when objs need to be removed from rendering info, but still exist.
        Mostly useful with clothing, and storing items, for now '''
        if self.x:
            g.M.tiles[self.x][self.y].objects.remove(self)

        self.x = None
        self.y = None

        if self in g.M.objects:
            g.M.objects.remove(self)

        if self in g.M.creatures:
            g.M.creatures.remove(self)

    def put_on_clothing(self, clothing):
        ''' Add this clothing to a parent object '''
        # Remove it from the map and handle some info about it
        ## TODO - fix awkward check about M
        if g.M is not None and clothing in g.M.objects:
            clothing.remove_from_map()

        clothing.being_worn = 1
        self.wearing.append(clothing)

        # Loops through all components in the wearable item,
        # and adds those layers onto the person wearing them
        for component in clothing.components:

            ## THIS FLAG IS ONLY FOR CLOTHING WHICH ADDS TO THE LAYERS
            if component.bodypart_covered:
                our_bodypart = self.get_component_by_name(component.bodypart_covered)

                ## This should add the clothing layers to whatever it covers
                ## TODO - unsure how to handle clothing with multiple components
                for layer in component.layers:
                    our_bodypart.add_material_layer(layer=layer, layer_is_inherent_to_object_component=0)

            ## THIS FLAG IS ONLY FOR WEARABLE THINGS WHICH DO NOT ADD TO LAYERS (like a backpack)
            elif component.bodypart_attached:
                attaches_to = component.bodypart_attached
                attach_strength = component.bodypart_attach_strength

                if attaches_to:
                    our_bodypart = self.get_component_by_name(component_name=attaches_to)
                    component.attach_to(our_bodypart, attach_strength)


    def take_off_clothing(self, clothing):
        ''' Remove this clothing from the parent object '''
        clothing.being_worn = 0
        # Remove from list of things parent is wearing
        self.wearing.remove(clothing)

        for component in clothing.components:

            ## THIS FLAG IS ONLY FOR CLOTHING WHICH ADDS TO THE LAYERS
            if component.bodypart_covered:
                our_bodypart = self.get_component_by_name(component.bodypart_covered)

                ## This should add the clothing layers to whatever it covers
                ## TODO - unsure how to handle clothing with multiple components
                for layer in reversed(component.layers):
                    our_bodypart.remove_material_layer(layer=layer)

            ## THIS FLAG IS ONLY FOR WEARABLE THINGS WHICH DO NOT ADD TO LAYERS (like a backpack)
            elif component.bodypart_attached:
                attaches_to = component.bodypart_attached
                attach_strength = component.bodypart_attach_strength

                if attaches_to:
                    our_bodypart = component.attached_to
                    component.disattach_from(our_bodypart)

        # Add it to the map
        g.M.add_object_to_map(x=self.x, y=self.y, obj=clothing)


    def get_component_by_name(self, component_name):
        ''' Given the name of a component, return the actual component '''
        for component in self.components:
            if component.name == component_name:
                return component

    def initial_give_object_to_hold(self, obj):
        ''' A bit of a hack for now, just to get the object holding a weapon '''
        for component in self.components:
            if 'grasp' in component.tags and not component.grasped_item:
                # Give 'em a sword
                self.pick_up_object(own_component=component, obj=obj)
                break


    def pick_up_object(self, own_component, obj):
        ''' Use the specified component to grasp an object '''
        if obj.being_grasped_by:
            obj.being_grasped_by.remove_grasp_on_item(obj)

        own_component.grasp_item(obj)

        obj.set_current_owner(self)
        obj.set_current_holder(self)

        ''' TODO - this is causing the game to freak out on worldmap view before a scale map has been created '''
        if g.game.map_scale == 'human':
            obj.remove_from_map()


    def drop_object(self, own_component, obj):
        ''' Drop an item, it will show up on the map '''
        own_component.remove_grasp_on_item(obj)
        # Add to the map wherever the owner is
        g.M.add_object_to_map(x=self.x, y=self.y, obj=obj)

        obj.clear_current_holder()

    def place_inside(self, own_component, other_object, grasping_component=None):

        available_volume = own_component.get_storage_volume()

        if other_object.get_volume() > available_volume:
            g.game.add_message(''.join([other_object.name, ' is too big to fit in the ', own_component.name]))
            return 0

        else:
            other_object.remove_from_map()
            # If we put something inside that we're already grasping, remove it
            # (otherwise, it's assumed we're gonna pick it up without the hastle of
            # clicking to grasp it, then clicking again to put it away
            if grasping_component is not None:
                grasping_component.remove_grasp_on_item(other_object)

            own_component.add_object_to_storage(other_object)

            g.game.add_message(''.join(['You place the ', other_object.name, ' in the ', own_component.name]))

            # This statement helps with menu items
            return 1

    def take_out_of_storage(self, other_object, grasping_component):
        other_object.inside.remove_object_from_storage(other_object)

        grasping_component.grasp_item(other_object)


    def get_stored_items(self):
        ''' Get everything stored inside us '''
        stored_items = []
        for component in self.components:
            if component.storage is not None:
                for obj in component.storage:
                    stored_items.append(obj)

        return stored_items

    def get_storage_items(self):
        ''' Returns a list of all items on our character which can store something '''
        storage_items = []
        for component in self.components:
            for attached_obj_comp in component.attachments:
                # Loop through objs to find components with storage
                if attached_obj_comp.storage is not None:
                    storage_items.append(attached_obj_comp)

        return storage_items

    def get_inventory(self):
        ''' return inventory
        Includes stuff we're wearing, and stuff we're grasping '''

        inventory = {'clothing':[], 'stored':[], 'grasped':[]}
        # Gather worn clothing
        #worn_clothing = []
        for clothing in self.wearing:
            inventory['clothing'].append(clothing)
            # Find if anything's stored within
            for item in clothing.get_stored_items():
                inventory['stored'].append(item)

        # Gather any items we're wearing
        #worn_items = []
        #for component in self.components:
        #    for obj_component in component.attachments:
        #        if obj_component.owner != component.owner:
        #            inventory['worn items'].append(obj_component.owner)

        # Build a list of things we're grasping
        graspers = self.creature.get_graspers()
        for component in graspers:
            if component.grasped_item is not None:
                inventory['grasped'].append(component.grasped_item)

                for item in component.grasped_item.get_stored_items():
                    inventory['stored'].append(item)

        return inventory

    def get_base_attack_value(self):
        # Base attack value is the object's mass. However,
        # if it wasn't specifically designed as a weapon,
        # that will be halved.
        if self.weapon:
            return self.get_mass()
        else:
            return self.get_mass() / 2


    def get_possible_target_components_from_attack_position(self, position):
        possible_target_components = []
        for component in self.components:
            if component.position == position or component.position is None:
                possible_target_components.append(component)

        return possible_target_components

    def get_wounds(self):
        wounds = []

        for component in self.components:
            for layer in component.layers:
                ## Ignores layers wihich aren't owned by the component (like cloth clothes are not owned by a creature's arm)
                if len(layer.wounds) and layer.owner == component:
                    for wound in layer.wounds:
                        wounds.append(wound)

        return wounds

    def get_wound_descriptions(self):
        wound_descripions = []

        for component in self.components:
            for layer in component.layers:
                ## Ignores layers wihich aren't owned by the component (like cloth clothes are not owned by a creature's arm)
                if len(layer.wounds) and layer.owner == component:
                    wound_descripions.append('{0} ({1}) - {2}'.format(component.name, layer.get_name(), layer.get_wound_descriptions()))

        return wound_descripions


    def get_mass(self):
        mass = 0
        for component in self.components:
            mass += component.get_mass()

        return mass

    def get_volume(self):
        volume = 0
        for component in self.components:
            volume += component.get_volume()

        return volume

    def get_density(self):
        mass = 0
        volume = 0
        for component in self.components:
            mass += component.get_mass()
            volume += component.get_volume()

        return mass / volume

    def destroy_component(self, component):
        ''' destroy a component of this object '''
        if component.attached_to is not None:
            component.disattach_from(component.attached_to)

        # Object kind of disintigrates... ???
        if component.attached_to is None:
            # Check if anything is in the list of attachments
            for other_component in component.attachments:
                other_component.disattach_from(component)
                g.game.add_message(other_component.name + ' has disattached from ' + component.name)

                # Each other component it's attached to becomes its own object
                other_component.attaches_to = None
                self.create_new_object_from_component(original_component=other_component)

        # This function should create a new object featuring the remains of this component
        # (and any other component attached to this one)
        self.create_new_object_from_component(original_component=component)

        # After creating the new object, destroy ourself
        # Some objects like wearable ones aren't in the list of objects on the map, so ignore those
        if self in g.M.objects and len(self.components) == 0:
            self.remove_from_map()


    def create_new_object_from_component(self, original_component):
        ''' If a component gets knocked off and we want to build a new object
        out of it, this is how we would do it '''

        # First, build a list of all components attached to the current one
        component_list = [original_component]

        found_additional_component = True
        while found_additional_component:
            found_additional_component = False

            for component in component_list:
                # Check if component is attached to anything
                if component.attached_to is not None and component.attached_to not in component_list:
                    found_additional_component = True
                    component_list.append(component.attached_to)
                # Check attachments
                for attached_component in component.attachments:
                    if attached_component not in component_list:
                        found_additional_component = True
                        component_list.append(attached_component)

        ## Make sure the component itself isn't set to attach to anything
        ## This prevents arms from trying to attach to phantom torsos, for example
        original_component.attaches_to = None

        # Now remove all of the components from the original object
        for component in component_list:
            self.components.remove(component)

        # Finally, create a new object at this location containing the components
        if self.name.endswith('remains'):
            logging.debug('Creating new object from %s' %self.name)
            new_name = self.name
        else:
            new_name = self.name + ' remains'
        #new_char = '%'
        new_char = self.char
        new_color = libtcod.color_lerp(libtcod.black, self.color, .5)

        ############# TODO - cleanup item location code so we don't need this verbose check for this item's location
        if self.x is None:
            if self.current_holder:
                # OK - no current location, but it has an owner we can piggyback from
                logging.warning('Creating new object - %s has no location, so using location of %s.' %(self.fullname(), self.fullname()) )
                x, y = self.current_holder.x, self.current_holder.y
            else:
                # Bad - there is no location info for object, and it does not have someone currently holding it
                logging.warning('Creating new object - %s has no location and no current holder!' %self.fullname() )
                x, y = 10, 10
        # This would ideally always happen - this object has a concrete location
        else:
            x, y = self.x, self.y
        ###############################################################################################################

        obj = Object(name=new_name, char=new_char, color=new_color,components=[],
                     blocks_mov=0, blocks_vis=0, description='This is a piece of %s'%self.fullname(), creature=None,
                     weapon=None, wearable=None)
        # I think this was done to prevent components trying to attach in weird ways when passed to the obj
        for component in component_list:
            obj.components.append(component)
            component.owner = obj

        g.M.add_object_to_map(x=x, y=y, obj=obj)


    def handle_chunk_move(self, x1, y1, x2, y2):
        ''' Handle this object moving between chunks of the world '''
        if g.M.tiles[x1][y1].chunk != g.M.tiles[x2][y2].chunk:
            g.M.tiles[x1][y1].chunk.objects.remove(self)
            g.M.tiles[x2][y2].chunk.objects.append(self)

    def move(self, dx, dy): #DON'T USE WITH A*,
        #move by the given amount, if the destination is not blocked
        blocks_mov = self.abs_pos_move(x=self.x+dx, y=self.y+dy)


    def move_and_face(self, dx, dy):
        #DON'T USE WITH A*,
        #move by the given amount, if the destination is not blocked
        blocks_mov = self.abs_pos_move(x=self.x+dx, y=self.y+dy)

        if not blocks_mov and (dx, dy) != (0, 0):
            # Face (index of direction we moved in)
            self.creature.facing = NEIGHBORS.index((dx, dy))

    '''
    def move_towards(self, target_x, target_y):
        #vector from this object to the target, and distance
        dx = target_x - self.x
        dy = target_y - self.y
        distance = math.sqrt(dx ** 2 + dy ** 2)

        #normalize it to length 1 (preserving direction), then round it and
        #convert to integer so the movement is restricted to the map grid
        dx = int(round(dx / distance))
        dy = int(round(dy / distance))
        self.move(dx, dy)

    def move_towards_f(self, target_x, target_y):
        #vector from this object to the target, and distance
        dx = target_x - self.x
        dy = target_y - self.y
        distance = math.sqrt(dx ** 2 + dy ** 2)

        #normalize it to length 1 (preserving direction), then round it and
        #convert to integer so the movement is restricted to the map grid
        dx = int(round(dx / distance))
        dy = int(round(dy / distance))
        self.move_and_face(dx, dy)
    '''


    def abs_pos_move(self, x, y): #USE WITH A*
        ''' The x and y vals here are actual x and y vals on the map '''
        blocks_mov = 1
        if not g.M.tile_blocks_mov(x, y):
            blocks_mov = 0

            g.M.tiles[self.x][self.y].objects.remove(self)
            libtcod.map_set_properties(g.M.fov_map, self.x, self.y, not g.M.tiles[self.x][self.y].blocks_vis, not g.M.tiles[self.x][self.y].blocks_mov)

            self.handle_chunk_move(self.x, self.y, x, y)

            self.x = x
            self.y = y
            libtcod.map_set_properties(g.M.fov_map, self.x, self.y, True, False)
            #libtcod.map_set_properties(M.fov_map, next_step[0], next_step[1], True, False)
            g.M.tiles[self.x][self.y].objects.append(self)

            ## For now, give other objects X and Y vals
            # TODO - make sure these are set when initially added to map
            for obj in self.wearing:
                obj.x = self.x
                obj.y = self.y

        return blocks_mov

    def set_astar_target(self, target_x, target_y, dbg_reason):
        g.game.add_message(dbg_reason, libtcod.color_lerp(self.color, libtcod.red, .5))
        g.game.add_message('{0} setting astar target ({1}, {2}): {3}'.format(self.fulltitle(), target_x, target_y, join_list([o.fulltitle() for o in g.M.tiles[target_x][target_y].objects])), self.color)
        ''' Sets a target using A*, includes flipping the target tile to unblocks_mov if it's a creature '''
        flip_target_tile = False
        # If the target is blocked, we need to temporarily set it to unblocked so A* can work
        if g.M.tile_blocks_mov(target_x, target_y) and get_distance_to(self.x, self.y, target_x, target_y) > 1:
            flip_target_tile = True
            libtcod.map_set_properties(g.M.fov_map, target_x, target_y, True, True)

        ai_move_path = libtcod.path_compute(g.M.path_map, self.x, self.y, target_x, target_y)
        ## v Old code from when this method actually moved the object
        #if ai_move_path and not libtcod.path_is_empty(M.path_map):
        #    x, y = libtcod.path_walk(M.path_map, True)
        #    blocks_mov = self.abs_pos_move(x=x, y=y)

        if flip_target_tile:
            # Flip the target's cell back to normal
            libtcod.map_set_properties(g.M.fov_map, target_x, target_y, True, False)

        self.cached_astar_path = libtcod_path_to_list(path_map=g.M.path_map)

    def move_with_stored_astar_path(self, path):
        #next_step = path.pop(0)
        #blocks_mov = self.abs_pos_move(x=next_step[0], y=next_step[1])
        if len(path):
            blocks_mov = self.abs_pos_move(x=path[0][0], y=path[0][1])
            if not blocks_mov:
                del path[0]

            return blocks_mov

        return 'path_end'


    def closest_creature(self, max_range, target_faction='enemies'):
        closest_enemy = None
        closest_dist = max_range + 1  #start with (slightly more than) maximum range

        if target_faction == 'enemies':
            for actor in g.M.creatures:
                if actor.creature.is_available_to_act() and self.creature.faction.is_hostile_to(actor.creature.faction): #and libtcod.map_is_in_fov(fov_map, object.x, object.y):
                    dist = self.distance_to(actor)
                    if dist < closest_dist:
                        closest_enemy = actor
                        closest_dist = dist

        else:
            for actor in g.M.creatures:
                if actor.creature.is_available_to_act() and actor.creature.faction == target_faction: #and libtcod.map_is_in_fov(fov_map, object.x, object.y):
                    #calculate distance between this object and the g.player
                    dist = self.distance_to(actor)
                    if dist < closest_dist:  #it's closer, so remember it
                        closest_enemy = actor
                        closest_dist = dist

        return closest_enemy, closest_dist

    def distance_to(self, other):
        #return the distance to another object
        dx = other.x - self.x
        dy = other.y - self.y
        return math.sqrt(dx ** 2 + dy ** 2)

    def distance(self, x, y):
        #return the distance to some coordinates
        return math.sqrt((x - self.x) ** 2 + (y - self.y) ** 2)

    ##### World-coords style ##############
    def w_distance_to(self, other):
        #return the distance to another object
        dx = other.wx - self.wx
        dy = other.wy - self.wy
        return math.sqrt(dx ** 2 + dy ** 2)

    def w_distance(self, x, y):
        #return the distance to some coordinates
        return math.sqrt((x - self.wx) ** 2 + (y - self.wy) ** 2)

    def w_handle_chunk_move(self, x1, y1, x2, y2):
        ''' Handle this object moving between chunks of the world '''
        if g.WORLD.tiles[x1][y1].chunk != g.WORLD.tiles[x2][y2].chunk:
            g.WORLD.tiles[x1][y1].chunk.entities.remove(self)
            g.WORLD.tiles[x2][y2].chunk.entities.append(self)

    def w_teleport(self, x, y):
        g.WORLD.tiles[self.wx][self.wy].entities.remove(self)

        self.w_handle_chunk_move(self.wx, self.wy, x, y)

        self.wx = x
        self.wy = y
        g.WORLD.tiles[self.wx][self.wy].entities.append(self)

        # Army status stuff
        self.world_last_dir = (0, 0)
        self.turns_since_move = 0

        if self.creature and self.creature.is_commander():
            for commanded_figure_or_population in self.creature.commanded_figures + self.creature.commanded_populations:
                commanded_figure_or_population.w_teleport(x, y)


    def w_move(self, dx, dy): #DON'T USE WITH A*,
        ''' Moves the army by the given xy coords, and handles updating the army's map info '''
        #self.check_for_army_dispatch()

        #move by the given amount, if the destination is not blocked
        if not g.WORLD.tile_blocks_mov(self.wx + dx, self.wy + dy):
            g.WORLD.tiles[self.wx][self.wy].entities.remove(self)

            self.w_handle_chunk_move(self.wx, self.wy, self.wx + dx, self.wy + dy)

            self.wx += dx
            self.wy += dy
            g.WORLD.tiles[self.wx][self.wy].entities.append(self)

            # Army status stuff
            self.world_last_dir = (-dx, -dy)
            self.turns_since_move = 0

            # Make sure to also move any units commanded with us
            if self.creature and (dx, dy) != (0, 0):
                for commanded_figure_or_population in self.creature.commanded_figures + self.creature.commanded_populations:
                    commanded_figure_or_population.w_move(dx=dx, dy=dy)

                # Update knowledge of sites
                self.creature.add_knowledge_of_sites_on_move(sites=g.WORLD.tiles[self.wx][self.wy].all_sites)

        #self.update_figures_and_check_for_city()

    def w_move_to(self, target_x, target_y):
        ''' Computes A* path and makes move '''
        ai_move_path = libtcod.path_compute(g.WORLD.path_map, self.wx, self.wy, target_x, target_y)
        if ai_move_path and not libtcod.path_is_empty(g.WORLD.path_map):
            x, y = libtcod.path_walk(g.WORLD.path_map, True)

            dx, dy = x - self.wx, y - self.wy
            self.w_move(dx, dy)

    def w_move_along_path(self, path):
        ''' Move along a predefined path (like roads between cities) '''
        # The path will be a list of tuples
        (x, y) = path.pop(0)
        dx, dy = x-self.wx, y-self.wy

        self.w_move(dx, dy)

    def w_draw(self):
        #only show if it's visible to the g.player
        #if libtcod.map_is_in_fov(fov_map, self.x, self.y):
        (x, y) = g.game.camera.map2cam(self.wx, self.wy)

        if x is not None:
            #set the color and then draw the character that represents this object at its position
            libtcod.console_set_default_foreground(g.game.interface.map_console.con, self.color)
            libtcod.console_put_char(g.game.interface.map_console.con, x, y, self.world_char, libtcod.BKGND_NONE)
            libtcod.console_put_char(g.game.interface.map_console.con, x+1, y, self.world_char+1, libtcod.BKGND_NONE)

    #### End moving world-coords style ########

    def draw(self):
        #only show if it's visible to the g.player
        if libtcod.map_is_in_fov(g.M.fov_map, self.x, self.y):
            (x, y) = g.game.camera.map2cam(self.x, self.y)

            if x is not None:
                #set the color and then draw the character that represents this object at its position
                libtcod.console_set_default_foreground(g.game.interface.map_console.con, self.display_color)
                libtcod.console_put_char(g.game.interface.map_console.con, x, y, self.char, libtcod.BKGND_NONE)
                libtcod.console_put_char(g.game.interface.map_console.con, x+1, y, self.char+1, libtcod.BKGND_NONE)

        elif not self.local_brain:
            (x, y) = g.game.camera.map2cam(self.x, self.y)

            if x is not None:
                libtcod.console_set_default_foreground(g.game.interface.map_console.con, self.shadow_color)
                #libtcod.console_set_default_foreground(con.con, self.dark_color)
                libtcod.console_put_char(g.game.interface.map_console.con, x, y, self.char, libtcod.BKGND_NONE)
                libtcod.console_put_char(g.game.interface.map_console.con, x+1, y, self.char+1, libtcod.BKGND_NONE)

    def clear(self):
        #erase the character that represents this object
        (x, y) = g.game.camera.map2cam(self.x, self.y)
        if x is not None:
            libtcod.console_put_char(g.game.interface.map_console.con, x, y, ' ', libtcod.BKGND_NONE)

    def firstname(self):
        if self.creature and self.creature.firstname:
            return self.creature.firstname
        else:
            return self.name

    def lastname(self):
        if self.creature and self.creature.lastname:
            return self.creature.lastname
        else:
            return self.name

    def fullname(self, use_you=0):
        if use_you and (g.player == self):
            return 'you'
        if self.creature and self.creature.firstname and self.creature.epithet: # and self.creature.status != 'dead':
            return '{0} \"{1}\" {2}'.format(self.creature.firstname, self.creature.epithet, self.creature.lastname)
        if self.creature and self.creature.firstname:
            return '{0} {1}'.format(self.creature.firstname, self.creature.lastname)
        else:
            return self.name

    def fulltitle(self, use_you=0):
        if use_you and (g.player == self):
            return 'you'
        if self.creature and self.creature.intelligence_level == 3:
            return '{0}, {1} {2}'.format(self.fullname(), lang.spec_cap(self.creature.type_), self.creature.get_profession())
        if self.creature and self.creature.intelligence_level == 2:
            return '{0}, {1} savage'.format(self.fullname(), lang.spec_cap(self.creature.type_))
        else:
            return self.name

    def get_weapon_properties(self):
        if self.weapon:
            return self.weapon['properties']
        # Empty properties if no weapon
        return {}



def attack_menu(actor, target):
    width = 48
    height = 50

    bwidth = width - (4 * 2)

    xb, yb = 0, 0
    transp = .8
    # Make the console window
    wpanel = gui.GuiPanel(width=width, height=height, xoff=xb, yoff=yb, interface=g.game.interface, is_root=0, append_to_panels=1, transp=.8)


    def button_refresh_func(target):
        width = 48
        height = 50

        bwidth = 20

        left_x = 2
        mid_x = 24
        right_x = 46

        left_y = 14
        mid_y = 14
        right_y = 14

        atx, aty = 4, 14
        # Setup buttons
        buttons = [gui.Button(gui_panel=wpanel, func=show_object_info, args=[target],
                                  text='Obj info', topleft=(mid_x, 40), width=bwidth, height=4, color=g.PANEL_FRONT, do_draw_box=True),
                   gui.Button(gui_panel=wpanel, func=g.game.interface.prepare_to_delete_panel, args=[wpanel],
                          text='X', topleft=(width-4, 1), width=3, height=3, color=g.PANEL_FRONT, do_draw_box=True)]

        ########## New simultaneous combat system preview ############
        weapon = g.player.creature.get_current_weapon()
        component = target.components[0] ##temp

        yval = 8
        for listed_combat_move in combat.melee_armed_moves:
            yval += 3
            xval = 2

            if listed_combat_move  not in g.player.creature.last_turn_moves:  button_color = g.PANEL_FRONT
            else:                                                   button_color = libtcod.dark_red

            #### Find parts which we can hit ####
            possible_target_components = target.get_possible_target_components_from_attack_position(position=listed_combat_move.position)
            can_hit = 'Can hit: {0}'.format(join_list(string_list=[c.name for c in possible_target_components]))
            #######################################

            if target.creature:
                odds = []
                # Go through each other combat move and find the odds
                for other_combat_move in combat.melee_armed_moves:
                    c1, c2 = combat.get_combat_odds(combatant_1=g.player, combatant_1_move=listed_combat_move, combatant_2=target, combatant_2_move=other_combat_move)
                    c1_total = max(1, sum(c1.values()))
                    c2_total = max(1, sum(c2.values()))
                    total_odds = c1_total/(c1_total + c2_total) * 100

                    odds_reasons = []
                    # Add the reasons/numbers contributing to the total odds
                    for reason, amt in c1.iteritems():
                        odds_reasons.append('++ {0} ({1})'.format(reason, amt))
                    for reason, amt in c2.iteritems():
                        odds_reasons.append('-- {0} ({1})'.format(reason, amt))

                    odds.append([listed_combat_move, other_combat_move, total_odds, odds_reasons])

                # Now sort the odds by the total_odds
                odds.sort(key=lambda sublist: sublist[2], reverse=True)

                #Flatten the odds list into a new list, hover_odds.
                # Hover_odds needs to just be a list of strings to pass as hover info.
                hover_odds = []
                for combat_move, other_combat_move, total_odds, odds_reasons in odds:
                    if other_combat_move not in target.creature.last_turn_moves:
                        hover_odds.append(' vs {1} ({2:.1f}%)'.format(combat_move.name, other_combat_move.name, total_odds))
                    else:
                        hover_odds.append('xxx vs {1} ({2:.1f}%) xxx'.format(combat_move.name, other_combat_move.name, total_odds))

                    for reason in odds_reasons:
                        hover_odds.append(reason)
                    hover_odds.append(' ')

            # Default hover text for when target is not a creature...
            else:
                hover_odds = ['{0} cannot fight back'.format(target.fullname())]


            buttons.append(gui.Button(gui_panel=wpanel, func=g.player.creature.set_combat_attack, args=[target, listed_combat_move, listed_combat_move],
                                   text=listed_combat_move.name, topleft=(xval, yval), width=20, height=3, color=button_color, do_draw_box=True,
                                   hover_header=[listed_combat_move.name, can_hit], hover_text=hover_odds, hover_text_offset=(30, 0)) )
        ######### End new simultaneous combat system preview #########

        mid_y += 4
        buttons.append(gui.Button(gui_panel=wpanel, func=g.game.interface.prepare_to_delete_panel, args=[wpanel],
                                  text='Cancel', topleft=(mid_x, 44), width=bwidth, height=4, color=g.PANEL_FRONT, do_draw_box=True))

        wpanel.gen_buttons = buttons


    def render_text_func(target):
        atx, aty = 4, 18
        ## Target and curent weapon info

        weapon = g.player.creature.get_current_weapon()
        attack_mods, defend_mods = g.player.creature.get_attack_odds(attacking_object_component=weapon.components[0],
                                                                    force=weapon.get_base_attack_value(), target=target, target_component=None)


        libtcod.console_print(wpanel.con, atx, 2, 'Target: ' + target.fullname())


        atk_tot = sum(attack_mods.values())
        dfn_tot = sum(defend_mods.values())

        libtcod.console_print(wpanel.con, atx, 4, 'General odds: %i (atk) and %i (dfn) = %01f ' \
                              %(atk_tot, dfn_tot, atk_tot / (atk_tot + dfn_tot) )  )

        y = 6
        libtcod.console_print(wpanel.con, atx, y, 'Attack - total: ' + str(sum(attack_mods.values())) )
        for mod, amt in attack_mods.iteritems():
            y += 1
            libtcod.console_print(wpanel.con, atx, y, mod + ': ' + str(amt) )


        y = 6
        libtcod.console_print(wpanel.con, atx + 22, y, 'Defense - total: ' + str(sum(defend_mods.values())))
        for mod, amt in defend_mods.iteritems():
            y += 1
            libtcod.console_print(wpanel.con, atx + 22, y, mod + ': ' + str(amt) )


    wpanel.update_button_refresh_func(button_refresh_func, [target])
    wpanel.update_render_text_func(render_text_func, [target])


def talk_screen(actor, target):
    width = 40

    xb, yb = 0, 0
    transp = .8
    # gui.Button 1 and 2 x vals
    b1x, b2x = 2, 15
    # gui.Button row 1 and 2 y vals
    row1y, row2y = 10, 14
    # Menu iten x and y vals
    atx, aty = 4, 15

    height = 50

    # Make the console window
    wpanel = gui.GuiPanel(width=width, height=height, xoff=xb, yoff=yb, interface=g.game.interface, name='talk_screen')

    def refresh_buttons():
        aty = 10
        buttons = [gui.Button(gui_panel=wpanel, func=g.game.interface.prepare_to_delete_panel, args=[wpanel],
                          text='X', topleft=(width-4, 1), width=3, height=3, color=g.PANEL_FRONT, do_draw_box=True)]

        talk_options = g.player.creature.get_valid_questions(target)

        for option in talk_options:
            button = gui.Button(gui_panel=wpanel, func=g.player.creature.ask_question, args=(target, option),
                                text=option, topleft=(atx, aty), width=16, height=3, color=g.PANEL_FRONT, do_draw_box=True)

            buttons.append(button)
            aty += 3

        #buttons.append(gui.Button(gui_panel=wpanel, func=recruit, args=[target], text='Recruit', origin=(atx, aty), width=6, tall=1, color=g.PANEL_FRONT, hcolor=libtcod.white, do_draw_box=True))
        buttons.append(gui.Button(gui_panel=wpanel, func=attack_menu, args=[g.player, target],
                                  text='Attack!', topleft=(atx, aty+3), width=16, height=3, color=g.PANEL_FRONT, do_draw_box=True, closes_menu=1))

        buttons.append(gui.Button(gui_panel=wpanel, func=order_menu, args=[g.player, target],
                                  text='Order', topleft=(atx, aty+6), width=16, height=3, color=g.PANEL_FRONT, do_draw_box=True, closes_menu=1))

        buttons.append(gui.Button(gui_panel=wpanel, func=g.game.render_handler.debug_dijmap_view, args=[target],
                                  text='See DMap', topleft=(atx, aty+9), width=16, height=3, color=g.PANEL_FRONT, do_draw_box=True))
        buttons.append(gui.Button(gui_panel=wpanel, func=g.game.interface.prepare_to_delete_panel, args=[wpanel],
                                  text='Done', topleft=(atx, aty+12), width=16, height=3, color=g.PANEL_FRONT, do_draw_box=True))

        wpanel.gen_buttons = buttons


    def render_panel_text():

        # Character name + title
        libtcod.console_print(wpanel.con, b1x, 2, target.fulltitle())
        libtcod.console_print(wpanel.con, b1x, 3, 'Age {0}'.format(target.creature.get_age()))

        # Dynasty
        if target.creature.dynasty:
            dynasty_info = '{0} dynasty'.format(target.creature.dynasty.lastname)
            libtcod.console_put_char_ex(wpanel.con, b1x, 4, target.creature.dynasty.symbol, target.creature.dynasty.symbol_color, target.creature.dynasty.background_color)
        else:
            dynasty_info = 'No major dynasty'
            libtcod.console_put_char_ex(wpanel.con, b1x, 4, target.creature.lastname[0], g.PANEL_FRONT, libtcod.darker_grey)

        libtcod.console_print(wpanel.con, b1x + 2, 4, dynasty_info)

        # Calculate some info about languages
        lang_info = 'Speaks {0}'.format(join_list([l.name for l in target.creature.languages]))
        written_langs = [l.name for l in target.creature.languages if target.creature.can_read(l)]
        written_lang_info = 'Can write {0}'.format(join_list(written_langs)) if written_langs else 'Illiterate'
        # Show the language information
        libtcod.console_print(wpanel.con, b1x, 5, lang_info)
        libtcod.console_print(wpanel.con, b1x, 6, written_lang_info)

        libtcod.console_print(wpanel.con, b1x, 7, ct('child', len(target.creature.children)))

    # Ugly ugly...
    wpanel.update_button_refresh_func(refresh_buttons, () )

    wpanel.update_render_text_func(render_panel_text, [] )



def order_menu(player, target):
    ''' Order for individual unit '''
    atx, aty = 4, 5

    height = 40
    width = 28

    bwidth = width - (4 * 2)

    wpanel = gui.GuiPanel(width=width, height=height, xoff=0, yoff=0, interface=g.game.interface)

    bx = 4
    by = 5

    wpanel.add_button(func=g.game.interface.prepare_to_delete_panel, args=[wpanel], text='Done', topleft=(bx, height-5), width=bwidth, height=3)
    wpanel.add_button(func=g.game.interface.prepare_to_delete_panel, args=[wpanel], text='X', topleft=(width-4, 1), width=3, height=3)


    wpanel.add_button(func=player_give_order, args=[target, 'move_to'], text='Move to...', topleft=(atx, aty), width=bwidth, height=3, closes_menu=1)
    wpanel.add_button(func=player_give_order, args=[target, 'follow'], text='Follow me', topleft=(atx, aty+3), width=bwidth, height=3 , closes_menu=1)


def player_give_order(target, order):
    ''' Interface to give the actual order selected from the menu '''
    if order == 'move_to':
        while 1:
            event = libtcod.sys_check_for_event(libtcod.EVENT_KEY_PRESS | libtcod.EVENT_MOUSE, key, mouse)
            mx, my = mouse.cx, mouse.cy
            x, y = g.game.camera.cam2map(mx, my)

            g.game.render_handler.render_all(do_flush=False)

            libtcod.console_print(con=g.game.interface.map_console.con, x=int(g.game.interface.map_console.width/2)-30, y=8, fmt='Click where you would like %s to move (right click to cancel)'%target.creature.firstname)
            ## Draw the path that the guy will take
            path = libtcod.path_compute(p=g.M.path_map, ox=target.x, oy=target.y, dx=x, dy=y)
            while not libtcod.path_is_empty(p=g.M.path_map):
                px, py = libtcod.path_walk(g.M.path_map, True)
                cpx, cpy = g.game.camera.map2cam(px, py)
                g.game.render_handler.render_tile(con=g.game.interface.map_console.con, x=cpx, y=cpy, c=g.PLUS_TILE, fore=libtcod.light_grey, back=libtcod.BKGND_NONE)

            # Draw the final location
            if mx % 2 != 0:
                mx -= 1
            g.game.render_handler.render_tile(con=g.game.interface.map_console.con, x=mx, y=my, c=g.X_TILE, fore=libtcod.grey, back=libtcod.black)

            if mouse.lbutton:
                g.player.creature.say('%s, move over there'%target.fullname())
                target.local_brain.set_state('moving', target_location=(x, y))
                break
            elif mouse.rbutton:
                break

            g.game.interface.map_console.blit()
            libtcod.console_flush()

            g.game.handle_fov_recompute()

    elif order == 'follow':
        target.local_brain.set_state('following', target_figure=g.player)
        g.player.creature.say('%s, follow me!'%target.fullname())

def player_order_follow():
    ''' Player orders all nearby allies to follow him '''
    g.player.creature.say('Everyone, follow me!')
    for figure in filter(lambda figure: figure.creature.commander == g.player and figure != g.player and figure.distance_to(g.player) <= 50 and figure.local_brain.perception_info['closest_enemy'] is None, g.M.creatures):
        figure.local_brain.set_state('following', target_figure=g.player)

def player_order_move():

    figures = filter(lambda figure: figure.local_brain and figure.creature.is_available_to_act() and figure.creature.commander == g.player, g.M.creatures)
    sq_size = int(round(math.sqrt(len(figures))))
    offset = int(sq_size/2)

    while 1:
        event = libtcod.sys_check_for_event(libtcod.EVENT_KEY_PRESS | libtcod.EVENT_MOUSE, key, mouse)
        mx, my = mouse.cx, mouse.cy
        x, y = g.game.camera.cam2map(mx, my)

        g.game.render_handler.render_all(do_flush=False)

        libtcod.console_print(con=g.game.interface.map_console.con, x=int(g.game.interface.map_console.width/2)-30, y=8, fmt='Click where you would like your army to move (right click to cancel)')

        # Draw the final location
        locs = []
        # TODO - this is off now with new 2-char-per-tile approach
        for i in xrange(mx-offset, mx+sq_size+1):
            for j in xrange(my-offset, my+sq_size+1):
                ii, jj = g.game.camera.cam2map(i, j)
                if not g.M.tile_blocks_mov(ii, jj):
                    locs.append((ii, jj))
                    g.game.render_handler.render_tile(con=g.game.interface.map_console.con, x=i, y=j, c=g.X_TILE, fore=libtcod.grey, back=libtcod.black)

        if mouse.lbutton_pressed and len(locs) >= len(figures):
            g.player.creature.say('Everyone, move over there')
            for i, figure in enumerate(figures):
                figure.local_brain.set_state('moving', target_location=locs[i])
            break

        elif mouse.lbutton_pressed:
            g.game.add_message('Location has too much blocking it to order entire group there', libtcod.darker_red)

        elif mouse.rbutton_pressed:
            break

        g.game.interface.map_console.blit()
        libtcod.console_flush()

        g.game.handle_fov_recompute()

def pick_up_menu():

    objs = [obj for obj in g.M.tiles[g.player.x][g.player.y].objects if obj != g.player]

    if len(objs) == 0:
        g.game.add_message('No objects to pick up at your location')
        return 'done'

    atx, aty = 4, 5

    height = 40
    width = 28

    bwidth = width - (4 * 2)

    wpanel = gui.GuiPanel(width=width, height=height, xoff=0, yoff=0, interface=g.game.interface)

    bx = 4
    by = 5

    wpanel.add_button(func=g.game.interface.prepare_to_delete_panel, args=[wpanel], text='Done', topleft=(bx, height-5), width=bwidth, height=3)
    wpanel.add_button(func=g.game.interface.prepare_to_delete_panel, args=[wpanel], text='X', topleft=(width-4, 1), width=3, height=3)

    y = 0
    for obj in objs:
        y += 5

        wpanel.add_button(func=storage_menu, args=[obj], text='Store ' + obj.name + '...',
                                          topleft=(atx, y), width=bwidth, height=4, closes_menu=1)
        # Hold in one of the hands
        for grasper in g.player.creature.get_graspers():
            if grasper.grasped_item is None:
                y += 5

                wpanel.add_button(func=g.player.pick_up_object, args=[grasper, obj], text='Hold ' + obj.name + ' in ' + grasper.name,
                                          topleft=(atx, y), width=bwidth, height=4, closes_menu=1)

        # Wear it, if possible
        if obj.wearable:
            y += 5

            wpanel.add_button(func=g.player.put_on_clothing, args=[obj], text='Wear the ' + obj.name,
                                      topleft=(atx, y), width=bwidth, height=4, closes_menu=1)


def manage_inventory():

    height = 40
    width = 28

    bx = 4
    by = 5

    b_width = width - (4 * 2)

    wpanel = gui.GuiPanel(width=width, height=height, xoff=0, yoff=0, interface=g.game.interface)

    def update_button_func():
        wpanel.gen_buttons = []

        inventory = g.player.get_inventory()

        # Setup buttons
        wpanel.add_button(func=g.game.interface.prepare_to_delete_panel, args=[wpanel], text='Done', topleft=(bx, height-5), width=b_width, height=3)
        wpanel.add_button(func=g.game.interface.prepare_to_delete_panel, args=[wpanel], text='X', topleft=(width-4, 1), width=3, height=3)

        y = 0
        for obj in inventory['clothing']:
            y += 3
            wpanel.add_button(func=g.player.take_off_clothing, args=[obj], text='Take off ' + obj.name, topleft=(bx, by+y), width=b_width, height=3)

        #draw_box(panel=root_con.con, x=bx-2, x2=bx+7+2, y=by-1, y2=i+1, color=libtcod.red)

        y += 3
        for obj in inventory['grasped']:
            y += 3
            wpanel.add_button(func=storage_menu, args=[obj], text='Store ' + obj.name + '...', topleft=(bx, by+y), width=b_width, height=3)
            y += 3
            wpanel.add_button(func=g.player.drop_object, args=[obj.being_grasped_by, obj], text='Drop ' + obj.name, topleft=(bx, by+y), width=b_width, height=3)

        y += 3
        for obj in inventory['stored']:
            for grasper in g.player.creature.get_graspers():
                if grasper.grasped_item is None:
                    y += 3
                    wpanel.add_button(func=g.player.take_out_of_storage, args=[obj, grasper], text='Hold ' + obj.name + '\n in ' + grasper.name, topleft=(bx, by+y), width=b_width, height=3)

        # Update gui panel buttons
        #wpanel.gen_buttons = buttons


    wpanel.update_button_refresh_func(update_button_func, () )


def storage_menu(obj):
    height = 40
    width = 28

    bx = 4
    by = 5

    b_width = width - (4 * 2)

    wpanel = gui.GuiPanel(width=width, height=height, xoff=0, yoff=0, interface=g.game.interface)

    ### Get a list of storage devices g.player might have
    storage_items = g.player.get_storage_items()

    buttons = [gui.Button(gui_panel=wpanel, func=g.game.interface.prepare_to_delete_panel, args=[wpanel], text='Done',
                          topleft=(bx, height-5), width=b_width, height=3, color=g.PANEL_FRONT, do_draw_box=True),
               gui.Button(gui_panel=wpanel, func=g.game.interface.prepare_to_delete_panel, args=[wpanel],
                          text='X', topleft=(width-4, 1), width=3, height=3, color=g.PANEL_FRONT, do_draw_box=True)]

    # Store item
    y = 0
    for component_with_storage in storage_items:
        y += 5
        buttons.append(gui.Button(gui_panel=wpanel, func=component_with_storage.owner.place_inside, args=[component_with_storage, obj],
                                  text='Place ' + obj.name + ' in ' + component_with_storage.name, topleft=(bx, y),
                                  width=b_width, height=4, color=g.PANEL_FRONT, do_draw_box=True, closes_menu=1))

    wpanel.gen_buttons = buttons


def choose_object_to_interact_with(objs, x, y):
    ''' There may be multiple objects to interact with on a given tile
    This function handles that. '''

    # Filter out the player as a possible object to interact with
    objs = [obj for obj in objs if obj != g.player]

    # If there's only one object, either talk to it or attack it (for now)
    if len(objs) == 1 and (not g.M.tiles[x][y].interactable and not objs[0].interactable):
        obj = objs[0]
        if obj.creature and obj.creature.status == 'alive':
            talk_screen(actor=g.player, target=obj)
        else:
            attack_menu(actor=g.player, target=obj)

    # Else, a button menu which shows the interactions
    else:
        (cx, cy) = g.game.camera.map2cam(x, y)

        height = 30
        width = 28

        bx = 4
        by = 0

        b_width = width - (4 * 2)

        wpanel = gui.GuiPanel(width=width, height=height, xoff=cx, yoff=cy, interface=g.game.interface)

        buttons = [gui.Button(gui_panel=wpanel, func=g.game.interface.prepare_to_delete_panel, args=[wpanel], text='Done',
                              topleft=(bx, height-5), width=b_width, height=3, color=g.PANEL_FRONT, do_draw_box=True),
                   gui.Button(gui_panel=wpanel, func=g.game.interface.prepare_to_delete_panel, args=[wpanel],
                          text='X', topleft=(width-4, 1), width=3, height=3, color=g.PANEL_FRONT, do_draw_box=True)]

        by = 0
        for obj in objs:
            if obj.creature and obj.creature.status == 'alive':
                by += 4
                buttons.append(gui.Button(gui_panel=wpanel, func=talk_screen, args=[g.player, obj],
                                  text='Talk to ' + obj.fullname(), topleft=(bx, by),
                                  width=b_width, height=4, color=g.PANEL_FRONT, do_draw_box=True, closes_menu=1))

            if obj.interactable:
                by += 4
                buttons.append(gui.Button(gui_panel=wpanel, func=obj.interactable['func'], args=obj.interactable['args'],
                                  text=obj.interactable['text'], topleft=(bx, by),
                                  width=b_width, height=4, color=g.PANEL_FRONT, do_draw_box=True, closes_menu=1))

            else:
                by += 4
                buttons.append(gui.Button(gui_panel=wpanel, func=attack_menu, args=[g.player, obj],
                                  text='Interact with ' + obj.fullname(), topleft=(bx, by),
                                  width=b_width, height=4, color=g.PANEL_FRONT, do_draw_box=True, closes_menu=1))

        # Specific tile interaction...
        if g.M.tiles[x][y].interactable:
            func = g.M.tiles[x][y].interactable['func']
            args = g.M.tiles[x][y].interactable['args']
            text = g.M.tiles[x][y].interactable['text']

            by += 4
            buttons.append(gui.Button(gui_panel=wpanel, func=func, args=args, text=text,
                                   topleft=(bx, by), width=b_width, height=3, color=g.PANEL_FRONT, do_draw_box=True, closes_menu=1))


        wpanel.gen_buttons = buttons


def debug_menu():
    height = 50
    width = 30

    wpanel = gui.GuiPanel(width=width, height=height, xoff=0, yoff=0, interface=g.game.interface)

    if g.game.map_scale == 'world':
        buttons = [gui.Button(gui_panel=wpanel, func=g.game.interface.prepare_to_delete_panel, args=[wpanel],
                 text='X', topleft=(width-4, 1), width=3, height=3, color=g.PANEL_FRONT, do_draw_box=True),

                   gui.Button(gui_panel=wpanel, func=list_people, args=[],
                 text='People', topleft=(3, 5), width=width-4, height=3, color=g.PANEL_FRONT, do_draw_box=True, closes_menu=1),

                    gui.Button(gui_panel=wpanel, func=list_factions, args=[],
                 text='Factions', topleft=(3, 8), width=width-4, height=3, color=g.PANEL_FRONT, do_draw_box=True, closes_menu=1)
                   ]
    elif g.game.map_scale == 'human':
        buttons = [gui.Button(gui_panel=wpanel, func=g.game.interface.prepare_to_delete_panel, args=[wpanel],
                 text='X', topleft=(width-4, 1), width=3, height=3, color=g.PANEL_FRONT, do_draw_box=True),

                 gui.Button(gui_panel=wpanel, func=list_people, args=[],
                 text='People', topleft=(3, 5), width=width-4, height=3, color=g.PANEL_FRONT, do_draw_box=True, closes_menu=1)
                   ]

    wpanel.gen_buttons = buttons


def list_people():
    height = 50
    width = 30

    wpanel = gui.GuiPanel(width=width, height=height, xoff=0, yoff=0, interface=g.game.interface)

    buttons = [gui.Button(gui_panel=wpanel, func=g.game.interface.prepare_to_delete_panel, args=[wpanel],
             text='X', topleft=(width-4, 1), width=3, height=3, color=g.PANEL_FRONT, do_draw_box=True)]

    y = 5
    for faction in g.WORLD.factions:

        leader = faction.get_leader()
        if leader is not None:
            y += 1
            buttons.append(gui.Button(gui_panel=wpanel, func=leader.creature.die, args=['godly debug powers'],
                 text=leader.fulltitle(), topleft=(2, y), width=width-4, height=1, color=g.PANEL_FRONT, do_draw_box=False) )

    wpanel.gen_buttons = buttons


def list_factions():
    height = 50
    width = 30

    wpanel = gui.GuiPanel(width=width, height=height, xoff=0, yoff=0, interface=g.game.interface)

    buttons = [gui.Button(gui_panel=wpanel, func=g.game.interface.prepare_to_delete_panel, args=[wpanel],
             text='X', topleft=(width-4, 1), width=3, height=3, color=g.PANEL_FRONT, do_draw_box=True)]

    y = 5
    for faction in g.WORLD.factions:

        y += 1
        buttons.append(gui.Button(gui_panel=wpanel, func=dbg_faction_relations, args=[faction],
             text='%s (%i)' % (faction.name, len(faction.members) ), topleft=(2, y), width=width-4, height=1, color=g.PANEL_FRONT, do_draw_box=False) )

    wpanel.gen_buttons = buttons


def dbg_faction_relations(faction):
    height = 50
    width = 30

    wpanel = gui.GuiPanel(width=width, height=height, xoff=30, yoff=0, interface=g.game.interface)

    buttons = [gui.Button(gui_panel=wpanel, func=g.game.interface.prepare_to_delete_panel, args=[wpanel],
             text='X', topleft=(width-4, 1), width=3, height=3, color=g.PANEL_FRONT, do_draw_box=True)]

    def render_text_func():
        y = 2

        libtcod.console_print(con=wpanel.con, x=2, y=y, fmt=faction.name)

        y += 3
        for other_faction in g.WORLD.factions:
            y += 1
            libtcod.console_print(con=wpanel.con, x=2, y=y, fmt=' - ' + other_faction.name + ' - ')

            relations = faction.get_faction_relations(other_faction)

            if relations != {}:
                for reason, amt in relations.iteritems():
                    y += 1
                    libtcod.console_print(con=wpanel.con, x=2, y=y, fmt='   -' + reason + ': ' + str(amt))

            else:
                y += 1
                libtcod.console_print(con=wpanel.con, x=2, y=y, fmt='No real relationship')

            y += 1

    wpanel.update_render_text_func(func=render_text_func, args=())
    wpanel.gen_buttons = buttons


class Population:
    def __init__(self, char, name, faction, creatures, sentients, econ_inventory, wx, wy, site=None, commander=None):
        self.char = char
        self.name = name
        self.faction = faction
        self.creatures = creatures
        # {culture:{race:{profession: amount}}}
        self.sentients = sentients
        self.econ_inventory = econ_inventory

        self.wx = wx
        self.wy = wy

        self.world_last_dir = (0, 0)
        self.turns_since_move = 0

        self.site = site
        self.commander = commander
        if self.commander:
            self.commander.creature.add_commanded_population(self)


    def get_number_of_beings(self):
        total_number = 0

        for culture in self.sentients:
            for race in self.sentients[culture]:
                for profession_name in self.sentients[culture][race]:
                    total_number += self.sentients[culture][race][profession_name]

        return total_number


    def w_handle_chunk_move(self, x1, y1, x2, y2):
        ''' Handle this object moving between chunks of the world '''
        if g.WORLD.tiles[x1][y1].chunk != g.WORLD.tiles[x2][y2].chunk:
            g.WORLD.tiles[x1][y1].chunk.populations.remove(self)
            g.WORLD.tiles[x2][y2].chunk.populations.append(self)

    def w_teleport(self, x, y):
        g.WORLD.tiles[self.wx][self.wy].populations.remove(self)
        self.w_handle_chunk_move(self.wx, self.wy, x, y)
        self.wx = x
        self.wy = y
        g.WORLD.tiles[self.wx][self.wy].populations.append(self)
        # Army status stuff
        self.world_last_dir = (0, 0)
        self.turns_since_move = 0


    def w_move(self, dx, dy):
        ''' Moves the population by the given xy coords, and handles updating the map info '''
        #move by the given amount, if the destination is not blocked
        if not g.WORLD.tile_blocks_mov(self.wx + dx, self.wy + dy):
            g.WORLD.tiles[self.wx][self.wy].populations.remove(self)
            self.w_handle_chunk_move(self.wx, self.wy, self.wx + dx, self.wy + dy)
            self.wx += dx
            self.wy += dy
            g.WORLD.tiles[self.wx][self.wy].populations.append(self)

            # Army status stuff
            self.world_last_dir = (-dx, -dy)
            self.turns_since_move = 0


    def add_to_map(self, startrect, startbuilding, patrol_locations, place_anywhere=0):
        ''' Add this population to the map '''
        allmembers = []

        for culture in self.sentients:
            for race in self.sentients[culture]:
                for profession_name in self.sentients[culture][race]:
                    for i in xrange(self.sentients[culture][race][profession_name]):
                        born = g.WORLD.time_cycle.years_ago(roll(20, 45))
                        human = culture.create_being(sex=1, born=born, dynasty=None, important=0, faction=self.faction, wx=self.wx, wy=self.wy, armed=1, race=race)
                        # TODO - this should be improved
                        human.creature.commander = self.commander

                        if profession_name is not None:
                            profession = Profession(name=profession_name, category='commoner')
                            profession.give_profession_to(figure=human)

                        #if self.origin_city:
                        #    human.creature.change_citizenship(new_city=self.origin_city, new_house=None)
                        allmembers.append(human)

        ####### PATROLS ####################
        for (lx, ly) in patrol_locations:
            radius = roll(35, 50)
            patrol_route = g.M.get_points_for_circular_patrol_route(center_x=lx, center_y=ly, radius=radius)
            g.game.add_message('Patrol route with radius of %i and length of %i generated'%(radius, len(patrol_route)), libtcod.orange)
            px, py = patrol_route[0]

            for i in xrange(3):
                figure = allmembers.pop(0)
                # Adding obj initializes the AI, so we can be ready to be setup for patrolling
                unblocked_locations = []
                for x in xrange(px-5, px+6):
                    for y in xrange(py-5, py+6):
                        if not g.M.tile_blocks_mov(x, y):
                            unblocked_locations.append((x, y))

                x, y = random.choice(unblocked_locations)
                g.M.add_object_to_map(x=x, y=y, obj=figure)

                figure.local_brain.set_state('patrolling', patrol_route=patrol_route)
        ####################################

        # Place somewhere in startling location that isn't blocked
        for figure in allmembers: #+ self.captives[:]:
            # Try 200 times to find a good spot in the starting area..
            found_spot = 0
            for counter in xrange(200):
                if startrect:
                    x, y = roll(startrect.x1, startrect.x2), roll(startrect.y1, startrect.y2)
                elif startbuilding:
                    x, y = random.choice(startbuilding.physical_property)
                ## place_anywhere used for battles at world-scale
                ## In those battles, only tiny maps are created, which is not enough so that each character has a unique spot
                if place_anywhere or not g.M.tile_blocks_mov(x, y):
                    found_spot = 1
                    break
            ####### Safety step - couldn't find a valid location ########
            if not found_spot:
                logging.debug('Could not place {0}, attempting to place nearby'.format(figure.fulltitle()) )
                # Now keep picking vals at random across the entire map ... one's bound to work
                while 1:
                    x, y = roll(10, g.M.width-11), roll(10, g.M.height-11)
                    if not g.M.tile_blocks_mov(x, y):
                        break
            ###### end safety step #####################################
            #if figure in self.captives:
            #    g.game.add_message('{0} is a captive and at {1}, {2}'.format(figure.fulltitle(), figure.x, figure.y))

            g.M.add_object_to_map(x=x, y=y, obj=figure)




class Dynasty:
    def __init__(self, lastname, race):
        self.lastname = lastname
        self.race = race

        g.WORLD.dynasties.append(self)

        self.members = []

        self.symbol = None
        self.primary_color = None
        self.background_color = None
        self.create_crest()

    def create_crest(self):
        # A crest to display as the dynasty symbol
        if roll(1, 10) == 1:
            self.symbol = self.lastname[0]
        else:
            self.symbol = chr(random.choice(g.DYNASTY_SYMBOLS))

        self.symbol_color = random.choice(g.DARK_COLORS)
        self.background_color = random.choice(g.LIGHT_COLORS)

        #def display_symbol(self, panel, x, y):
        #libtcod.console_put_char_ex(panel, x, y, self.symbol, self.symbol_color, self.background_color)
        #libtcod.console_blit(panel, 0, 0, g.SCREEN_WIDTH, g.SCREEN_HEIGHT, 0, 0, 0)


class Creature:
    def __init__(self, type_, sex, intelligence_level, firstname=None, lastname=None, culture=None, born=None, dynasty=None, important=0):
        self.type_ = type_
        self.sex = sex
        self.intelligence_level = intelligence_level

        self.next_tick = 1
        self.turns_since_move = 0


        self.current_weapon = None
        self.status = 'alive'

        self.flags = {'has_shelter': 0}

        self.combat_target = []
        self.needs_to_calculate_combat = 0
        self.last_turn_moves = []

        self.natural_combat_moves = {
                             'bite': 10,
                             'high punch': 100,
                             'middle punch': 100,
                             'low punch': 100,
                             'kick': 100
                             }


        # Any languages we speak will go here.
        # Will be structured as self.languages[language][mode] = skill_level, where mode is 'verbal' or 'written'
        self.languages = {}

        self.skills = {}
        for skill, value in phys.creature_dict[self.type_]['creature']['skills'].iteritems():
            self.skills[skill] = value


        self.experience = {}
        for skill, value in self.skills.iteritems():
            self.experience[skill] = EXPERIENCE_PER_SKILL_LEVEL[value] - 1


        self.attributes = {}
        for attribute, value in phys.creature_dict[self.type_]['creature']['attributes'].iteritems():
            self.attributes[attribute] = value

        self.alert_sight_radius = g.ALERT_FOV_RADIUS
        self.unalert_sight_radius = g.UNALERT_FOV_RADIUS


        self.pain = 0
        ## Blood ##
        self.blood = 5.6 # in liters - should also scale with body's volume
        self.max_blood = self.blood
        self.bleeding = 0
        self.clotting = .05

        self.set_stance(random.choice(('Aggressive', 'Defensive')) )
        # 8 cardinal directions, 0 = north, every +1 is a turn clockwise
        self.facing = 0

        # To be set later
        self.dijmap_desires = {}

        # To be set when it is added to the object component
        self.owner = None

        ###################### Sapient #####################

        self.culture = culture
        self.born = born

        self.dynasty = dynasty

        self.important = important
        self.generation = 0

        # Relationships with others beyond trait clashes
        self.extra_relations = {}
        self.knowledge = {  'entities': {},
                            'objects': {},
                            'events': {},
                            'sites': {}
                            }

        # People we've recently conversed with
        self.recent_interlocutors = []
        # Pending conversation responses
        self.pending_conversations = []

        # Stuff for capturing people
        self.captor = None
        # Keeps track of people who are captive, even if they're not directly with us
        # (like they're in our house or something)
        self.captives = []

        self.faction = None

        self.commander = None
        self.commanded_populations = []
        self.commanded_figures = []

        self.economy_agent = None
        self.econ_inventory = defaultdict(int)
        self.net_money = 0

        self.home_site = None # Where we originally were from
        self.current_citizenship = None # The city where our house is currently located
        self.current_lodging = None # The place where we are currently staying - will be None when travelling,
        # our house if we're in our home city, or can be an inn

        self.firstname = firstname
        self.lastname = lastname
        self.epithet = None

        # Family stuff
        self.mother = None
        self.father = None
        self.spouse = None
        self.children = []
        self.siblings = []
        self.inheritance = {} # dict

        self.house = None
        self.profession = None

        self.traits = {}
        self.goals = []
        self.opinions = {}

        # Objects that we own
        self.possessions = set([])
        self.former_possessions = set([])

        # Pick some traits
        self.set_initial_traits()
        ## Set initial opinions - this is without having a profession
        self.set_opinions()

    def can_read(self, language):
        return language in self.languages and self.languages[language]['written'] > 0


    def update_language_knowledge(self, language, verbal=0, written=0):
        if language in self.languages:
            self.languages[language]['verbal'] += verbal
            self.languages[language]['written'] += written
        else:
            self.languages[language] = {}
            self.languages[language]['verbal'] = verbal
            self.languages[language]['written'] = written

    def modify_experience(self, skill, amount):
        self.experience[skill] += amount

        # If the amount of experience is greater than the amount of xp needed to get to the next level
        if self.experience[skill] >= EXPERIENCE_PER_SKILL_LEVEL[self.skills[skill]] and self.skills[skill] <= MAX_SKILL_LEVEL:
            self.skills[skill] += 1

            # Notify g.player
            if self.owner == g.player:
                g.game.add_message(new_msg="You have increased {0} to {1}".format(skill, self.skills[skill]), color=libtcod.green)

    def check_to_perceive(self, other_creature):

        perceived = 0
        threat_level = -1

        if self.owner.distance_to(other_creature) < self.unalert_sight_radius:
            line = libtcod.line_init(self.owner.x, self.owner.y, other_creature.x, other_creature.y)
            perceived = 1
            # Raycast from our position to see if any obstacles block our vision
            x, y = libtcod.line_step()
            while x is not None:
                if g.M.tile_blocks_sight(x, y):
                    perceived = 0
                    break

                x, y = libtcod.line_step()

        return perceived, threat_level

    def set_initial_desires(self, factions_on_map):

        ## TODO - more elegant way to become aware of all factions
        ## !! currently doesn't know about any factions other than ourselves and enemies
        self.dijmap_desires =     {
                                   self.owner.creature.faction.name:0,
                                   'map_center':0
                                  }


        for faction in factions_on_map:
            self.dijmap_desires[faction.name] = 0


    def handle_tick(self):

        #self.move_action_pool += self.catts['Move Speed']
        #self.attack_action_pool += self.catts['Attack Speed']


        if self.bleeding:
            self.bleed()
            ## Add some blood
            #blood_amt = min(actor.creature.bleeding/100, 1)
            blood_amt = .1
            #M.tiles[self.owner.x][self.owner.y].color = libtcod.color_lerp(M.tiles[self.owner.x][self.owner.y].color, libtcod.darker_red, blood_amt)
            g.M.tiles[self.owner.x][self.owner.y].set_color(color=libtcod.color_lerp(g.M.tiles[self.owner.x][self.owner.y].color, libtcod.darker_red, blood_amt) )


    def is_available_to_act(self):
        ''' Way to check whether the figure can act of their own accord.'''
        return not (self.owner.creature.is_captive() or self.status in ('unconscious', 'dead'))

    def set_status(self, status):
        self.status = status

    def set_stance(self, stance):
        self.stance = stance

    def get_graspers(self):
        return [component for component in self.owner.components if 'grasp' in component.tags]

    def set_combat_attack(self, target, opening_move, move2):
        self.needs_to_calculate_combat = 1
        self.combat_target = [target, opening_move, move2]

    def set_last_turn_moves(self, moves):
        self.last_turn_moves = moves

    def get_defense_score(self):

        return_dict = {
                       'fighting skill':self.skills['fighting'],
                       'parrying skill':self.skills['parrying'],
                       'dodging skill':self.skills['dodging']
                       }

        return return_dict


    def get_attack_score(self, verbose=0):

        return_dict = {self.stance + ' stance':g.STANCES[self.stance]['attack_bonus'],
                       'fighting skill':self.skills['fighting']
                       }

        return return_dict

    def get_current_weapon(self):
        if self.current_weapon is not None:
            return self.current_weapon

        elif self.current_weapon is not None:
            # See if we're holding any item
            for grasper in self.get_graspers():
                if grasper.grasped_item is not None:
                    return grasper.grasped_item

        ## TODO - this is weird...
        ## Kind of simulates unarmed combat - will return the object and thus use the first component as a weapon
        else:
            return self.owner
        #return None

    def dijmap_move(self):
        """ Move via use of dijisktra maps. There's a separate map for each desire, and we just sum
        each map, multiply by the weight of each desire, and roll downhill """
        i, j = (self.owner.x, self.owner.y)
        nx = i
        ny = j

        current_tile_cost = 0
        for desire, amount in self.dijmap_desires.iteritems():
            if g.M.dijmaps[desire].dmap[i][j] is not None:
                current_tile_cost += (g.M.dijmaps[desire].dmap[i][j] * amount)

        # Find any neighbors with a cost less than current
        for (x, y) in ( (i - 1, j - 1), (i, j - 1), (i + 1, j - 1),
                        (i - 1, j),                 (i + 1, j),
                        (i - 1, j + 1), (i, j + 1), (i + 1, j + 1) ):

            if g.M.is_val_xy((x, y)):  # and not g.M.tile_blocks_mov(x, y): #not g.M.tiles[x][y].blocked:
                ## Check each desire, multiply by amount, and save if necessary
                weighted_desire = 0
                for desire, amount in self.dijmap_desires.iteritems():
                    if g.M.dijmaps[desire].dmap[x][y] is not None:
                        weighted_desire += (g.M.dijmaps[desire].dmap[x][y] * amount)
                    ## Only move if we have a reason to
                if weighted_desire < current_tile_cost and not g.M.tile_blocks_mov(x, y):
                    current_tile_cost = weighted_desire
                    nx, ny = (x, y)

        if (nx, ny) != (self.owner.x, self.owner.y):
            # Once the spot is picked, move there
            self.owner.abs_pos_move(x=nx, y=ny)

            self.turns_since_move = 0
        else:
            self.turns_since_move += 1


    def face(self, other):
        # Face an object
        # Start by calculating where we'd have to move
        dx = other.x - self.owner.x
        dy = other.y - self.owner.y
        distance = math.sqrt(dx ** 2 + dy ** 2)
        #normalize it to length 1 (preserving direction), then round it and
        #convert to integer so the movement is restricted to the map grid
        dx = int(round(dx / distance))
        dy = int(round(dy / distance))

        self.facing = NEIGHBORS.index((dx, dy))


    def get_attack_odds(self, attacking_object_component, force, target, target_component):
        ''' Gets attack odds, returning a breakdown as a dict if verbose is selected '''

        attack_score = self.get_attack_score()

        if target.creature:
            defend_score = target.creature.get_defense_score()
        else:
            #defend_score = {}
            # Adding default for now...
            defend_score = {'Providing default value here': 1}

        # Compare volume of volume of the creature to the volume of the target component
        # This difference becomes a defense modifier
        '''if target_component:
            #volume_mod = int( (target_component.get_volume() / self.owner.get_volume()) )
            volume_mod = int( self.owner.get_volume() / target_component.get_volume() )
            #print volume_mod

            defend_score['Vol. size bonus'] = volume_mod
        '''

        return attack_score, defend_score



    def handle_renegade_faction(self, target):
        utterance = random.choice(('HEY!', 'WHAT ARE YOU DOING?!', 'AAAAHHHH!!!'))
        target.creature.say(utterance)

        if target.creature.current_weapon is not None and target.creature.current_weapon.weapon:
            target.local_brain.set_state('attacking')
        else:
            target.local_brain.set_state('fleeing')


    def simple_combat_attack(self, combat_move, target):
        combat_log = []


        if target.creature and not self.owner.creature.faction.is_hostile_to(target.creature.faction) and target.local_brain and target.local_brain.ai_state == 'idle':
            self.handle_renegade_faction(target)

        # Hacking in some defaults for now
        attacking_weapon = self.get_current_weapon()
        attacking_object_component = attacking_weapon.components[0]
        force = attacking_weapon.get_mass() * (roll(100, 160)/10)

        # Calculate the body parts that can be hit from this attack
        # TODO - needs to handle targets which don't have any valid componenets
        possible_target_components = target.get_possible_target_components_from_attack_position(position=combat_move.position)
        target_component = random.choice(possible_target_components)


        # Find chances of attack hitting
        attack_modifiers, defend_modifiers = self.get_attack_odds(attacking_object_component=attacking_object_component, force=force, target=target, target_component=target_component)

        attack_chance = sum(attack_modifiers.values())
        defend_chance = int(sum(defend_modifiers.values())/2)

        if roll(1, attack_chance + defend_chance) < attack_chance:
            chances_to_hit = target_component.get_chances_to_hit_exposed_layers()
            # Weighted choice, from stackoverflow
            targeted_layer = weighted_choice(chances_to_hit)

            # Use the poorly-written physics module to compute damage
            target_component.apply_force(other_obj_comp=attacking_object_component, total_force=force, targeted_layer=targeted_layer)

            if targeted_layer.owner == target_component:
                preposition = 'on'
            else:
                preposition = 'covering'

            combat_log.append(('{0}\'s {1} with {2} {3} hits the {4} {5} {6}\'s {7}.'.format(self.owner.fullname(), combat_move.name, 'his', self.get_current_weapon().name,
                                targeted_layer.get_name(), preposition, target.fullname(), target_component.name), self.owner.color))

        # Attack didn't connect
        else:
            combat_log.append(('{0} dodged {1}\'s attack!'.format(target.fullname(), self.owner.fullname()), target.color))


        ## Modify creature's XP
        self.modify_experience(skill='fighting', amount=5)
        ## Can't modify experience if we attack an inanimate object
        if target.creature:
            target.creature.modify_experience(skill='fighting', amount=5)

        return combat_log


    def cause_to_bleed(self, damage, sharpness):
        #self.bleeding = min(damage*sharpness, self.max_blood)
        self.bleeding = min(sharpness-1, self.max_blood)

    def bleed(self):
        ''' Taking damage can cause us to bleed, this function handles that '''
        self.blood = max(self.blood - self.bleeding, 0)
        # Clot
        self.bleeding = max(self.bleeding - self.clotting, 0)

        # Do we die?
        if self.blood < 3 and self.status == 'alive':
            self.pass_out(reason='loss of blood')
        elif self.blood < 2:
            self.die(reason='blood loss')

    def evaluate_wounds(self):
        max_number_of_grievous_wounds = 2

        total_number_of_grievous_wounds = 0

        # Bad way to check wound seriousness
        for wound in self.owner.get_wounds():
            if wound.damage < 20:
                total_number_of_grievous_wounds += .1
            elif wound.damage < 50:
                total_number_of_grievous_wounds += .25
            elif wound.damage < 80:
                total_number_of_grievous_wounds += .5
            else:
                total_number_of_grievous_wounds += 1

        # Pass out from wounds
        if total_number_of_grievous_wounds >= max_number_of_grievous_wounds:
            self.pass_out(reason='overwhelming damage infliction')

        # TODO - replace this useless function with sane damage modeling
        self.increment_pain(damage=.2, sharpness=1.1)


    def increment_pain(self, damage, sharpness):
        self.pain = min(self.pain + damage, self.get_max_pain() )

        if sharpness > 1:
            self.cause_to_bleed(damage, sharpness)

        self.handle_pain_effects(damage, sharpness)

    def get_pain(self):
        return self.pain

    def get_max_pain(self):
        return 1 + int(self.attributes['willpower']/10)

    def get_pain_ratio(self):
        return self.get_pain() / self.get_max_pain()

    def handle_pain_effects(self, damage, sharpness):
        pain_ratio = self.get_pain_ratio()

        # Potentially pass out
        if pain_ratio > .95 and self.status == 'alive':
            self.pass_out(reason='pain')

        if self.status == 'alive' and self.owner.creature:
            self.owner.creature.verbalize_pain(damage, sharpness, pain_ratio)


    def pass_out(self, reason):
        self.set_status('unconscious')
        self.set_stance('Prone')

        # Drop any things we have
        for component in self.get_graspers():
            if component.grasped_item is not None:
                # Drop the object (and release hold on it)
                self.owner.drop_object(own_component=component, obj=component.grasped_item)

        self.owner.set_display_color(self.owner.pass_out_color)
        self.owner.creature.nonverbal_behavior('passes out due to %s' %reason, libtcod.darker_red)


    #def add_enemy_faction(self, faction):
    #    self.enemy_factions.add(faction)

    #def remove_enemy_faction(self, faction):
    #    self.enemy_factions.remove(faction)

    def threatens_economic_output(self):
        return len(self.commanded_figures) > 20

    def is_commander(self):
        return len(self.commanded_figures) or len(self.commanded_populations)

    def get_total_number_of_commanded_beings(self):
        ''' Returns the number of beings under tis character's command'''
        if self.is_commander():
            number_of_figures = len(self.commanded_figures)
            total_number = number_of_figures + 1 #(add 1, which is ourself)
            # Dig down into the population breakdown to get the total number
            for population in self.commanded_populations:
                total_number += population.get_number_of_beings()
        # If we're not a commander, return 0, meaning no men under our command
        else:
            total_number = 0

        return total_number

    def add_commanded_figure(self, figure):
        figure.creature.commander = self.owner
        self.commanded_figures.append(figure)

    def remove_commanded_figure(self, figure):
        figure.creature.commander = None
        self.commanded_figures.remove(figure)

    def add_commanded_population(self, population):
        population.commander = self.owner
        self.commanded_populations.append(population)

    def remove_commanded_population(self, population):
        population.commander = None
        self.commanded_populations.remove(population)

    def get_base_detection_chance(self):
        ''' Chance (out of 100) that this being will be detected when another unit shares the world tile with it'''
        pass

    #def handle_question(self, asker, target, question_type):
    #    ''' Handles all functions relating to asking questions '''
    #    # First determine answer ('no response', 'truth', later will implement 'lie')
    #    # This also handles updating knowledge
    #    answer_type = self.ask_question(asker=asker, target=target, question_type=question_type)
    #    # Verbal responses to the questions
    #    if g.player in self.participants:
    #        self.verbalize_question(asker=asker, target=target, question_type=question_type)
    #        self.verbalize_answer(asker=asker, target=target, question_type=question_type, answer_type=answer_type)

    def buy_object(self, obj, sell_agent, price, material=None, create_object=1):

        # First create the object if it doesn't exist
        if create_object:
            obj = assemble_object(object_blueprint=phys.object_dict[obj], force_material=material, wx=self.owner.wx, wy=self.owner.wy)

        # Decrement object form owner's inventory
        sell_agent.sell_inventory[sell_agent.sold_commodity_name] -= 1

        sell_agent.adjust_gold(price)

        #own_component = [grasper for grasper in self.get_graspers() if not grasper.grasped_item][0]
        #self.owner.pick_up_object(own_component=own_component, obj=obj)
        self.owner.initial_give_object_to_hold(obj)

        return obj

    def ask_question(self, target, question_type):
        ''' Handles the information transfer between questions.
        The verbalization component is handled in the "verbalize" functions '''
        # Send the prompt over to the target
        self.verbalize_question(target, question_type)

        target.creature.pending_conversations.append((self.owner, question_type))

        # TODO - move this g.player-specific bit somewhere where it makes more sense?
        if self.owner == g.player:
            g.game.player_advance_time(ticks=1)


    def verbalize_question(self, target, question_type):
        # Ask the question
        g.game.add_message(self.owner.fullname() + ': ' + g.CONVERSATION_QUESTIONS[question_type], libtcod.color_lerp(self.owner.color, g.PANEL_FRONT, .5))


    def verbalize_answer(self, asker, question_type, answer_type):
        ''' Sending the answer through the game messages '''

        if answer_type == 'no answer':
            self.say('I don\'t want to tell you that.')

        elif answer_type == 'truth':
            if question_type == 'name':
                self.say('My name is %s.' % self.owner.fullname() )

            elif question_type == 'profession':
                if self.profession:
                    self.say('I am {0}'.format(indef(self.profession.name)))
                else:
                    self.say('I do not have any profession.')

            elif question_type == 'battles':
                found_event = 0
                for event_id in self.get_knowledge_of_events(days_ago=360):
                    if hist.historical_events[event_id].type_ == 'battle':
                        found_event = 1
                        self.say(hist.historical_events[event_id].describe())
                        self.say('I heard this from {0} on {1}'.format(self.knowledge['events'][event_id]['description']['source'].fulltitle(),
                                                                        g.WORLD.time_cycle.date_to_text(self.knowledge['events'][event_id]['description']['date_learned'])))
                if not found_event:
                    self.say('I don\'t know of any recent battles.')

            elif question_type == 'events':
                found_event = 0
                other_event_types = ('marriage', 'birth', 'death', 'travel_start', 'travel_end')
                for event_id in self.get_knowledge_of_events(days_ago=360):
                    if hist.historical_events[event_id].type_ in other_event_types:
                        found_event = 1
                        self.say(hist.historical_events[event_id].describe())
                        self.say('I heard this from {0} on {1}'.format(self.knowledge['events'][event_id]['description']['source'].fulltitle(),
                                                                        g.WORLD.time_cycle.date_to_text(self.knowledge['events'][event_id]['description']['date_learned'])))
                if not found_event:
                    self.say('I haven\'t heard of anything going on recently')

            elif question_type == 'sites':
                found_site = 0
                sites = []
                hostile_sites = []
                site_at_entity_location = g.WORLD.tiles[self.owner.wx][self.owner.wy].site

                if site_at_entity_location not in self.knowledge['sites']:
                    logging.warning('{0} doesn\'t know about {1}, despite being at that location'.format(self.owner.fulltitle(), site_at_entity_location.get_name()))

                for site in self.knowledge['sites']:
                    if site.get_faction() and self.owner.creature.faction.is_hostile_to(site.get_faction()):
                        hostile_sites.append(site)
                    else:
                        sites.append(site)


                if site_at_entity_location:
                    self.say('We are currently in {0}'.format(site_at_entity_location.get_name()))

                for site in itertools.chain(sites, hostile_sites):
                    if site.name: name = ' called {0}'.format(site.name)
                    else:         name = ''
                    self.say('I know of {0}{1} located in {2}'.format(indef(site.type_), name, g.WORLD.tiles[site.x][site.y].get_location_description_relative_to((self.owner.wx, self.owner.wy)) ))


                if not sites and not hostile_sites:
                    self.say('I actually don\'t know about any sites at all')

            elif question_type == 'age':
                age = self.get_age()
                self.say('I am %i.' % age)

            elif question_type == 'city':
                current_citizen_of = self.current_citizenship

                if current_citizen_of:
                    self.say('I currently live in %s.' % current_citizen_of.name)
                else:
                    self.say('I currently do not hold any citizenship.')

            elif question_type == 'goals':
                if len(self.owner.world_brain.current_goal_path):
                    if len(self.owner.world_brain.current_goal_path) == 1:
                        self.say('My current goal is to {0}.'.format(self.owner.world_brain.current_goal_path[0].get_name()) )
                    elif len(self.owner.world_brain.current_goal_path) > 1:
                        goal_names = join_list([goal.get_name() for goal in self.owner.world_brain.current_goal_path[1:]])
                        self.say('My current plan is to {0}. Later, I\'m going to {1}'.format(self.owner.world_brain.current_goal_path[0].get_name(), goal_names))
                # IF we're travelling under someone's command
                elif self.commander and len(self.commander.world_brain.current_goal_path):
                    if len(self.commander.world_brain.current_goal_path) == 1:
                        self.say('I\'m with {0}. Our current plan is to {1}.'.format(self.commander.fullname(), self.commander.world_brain.current_goal_path[0].get_name()) )
                    elif len(self.commander.world_brain.current_goal_path) > 1:
                        goal_names = join_list([goal.get_name() for goal in self.commander.world_brain.current_goal_path[1:]])
                        self.say('I\'m with {0}. Our current plan is to {1}. Later, we\'ll {2}'.format(self.commander.fullname(), self.commander.world_brain.current_goal_path[0].get_name(), goal_names))
                else:
                    self.say('I don\'t really have any goals at the moment.')

            else:
                self.say('I am not yet programmed to answer that')

        ## Shouldn't break the mold here... but answer_type is different
        if question_type == 'recruit':
            if answer_type == 'yes':
                self.say('I will gladly join you!')
                ### TODO - put this into a function!
                self.profession = Profession('Adventurer', 'commoner')
                g.player.creature.add_commanded_figure(self.owner)

            elif answer_type == 'no':
                ## Decline, with a reason why
                if self.commander:
                    self.say('I am already a member of %s.' % self.commander.name)
                elif self.get_profession:
                    self.say('As {0}, I cannot join you.'.format(indef(self.get_profession() )))
                else:
                    self.say('I cannot join you.')

        # Same with greetings...
        elif question_type == 'greet':
            if answer_type == 'return greeting':
                self.say('Hello there.')
            elif answer_type == 'no answer':
                self.nonverbal_behavior('does not answer')
            elif answer_type == 'busy':
                self.say('I\m sorry, I am busy right now.')


    def get_valid_questions(self, target):
        ''' Valid questions to ask '''
        valid_questions = []
        if target not in self.recent_interlocutors:
            return ['greet']

        if target not in self.knowledge['entities']:
            return ['name']

        if target.get_inventory()['stored']:
            valid_questions.append('trade')

        if self.knowledge['entities'][target]['stats']['city'] is None:
            valid_questions.append('city')

        if self.knowledge['entities'][target]['stats']['age'] is None:
            valid_questions.append('age')

        if self.knowledge['entities'][target]['stats']['profession'] is None:
            valid_questions.append('profession')

        if self.knowledge['entities'][target]['stats']['goals'] is None:
            valid_questions.append('goals')

        valid_questions.append('events')
        valid_questions.append('battles')
        valid_questions.append('sites')

        ## TODO - allow NPCs to recruit, under certain circumstances
        if self.is_commander() and target.creature.commander != self.owner and self.owner == g.player:
            valid_questions.append('recruit')

        return valid_questions


    #def get_valid_topics(self, target):
    #    ''' Valid topics of conversation '''
    #    return self.topics

    #def change_topic(self, topic):
    #    self.topic = topic
    #    g.game.add_message('You begin talking about ' + self.topic + '.', libtcod.color_lerp(g.player.color, g.PANEL_FRONT, .5))


    def determine_response(self, asker, question_type):

        if question_type == 'greet':
            self.recent_interlocutors.append(asker)
            asker.creature.recent_interlocutors.append(self.owner)

            return 'return greeting'

        elif question_type == 'name':
            ''' Ask the target's name '''
            asker.creature.meet(self.owner)

            return 'truth'

        elif question_type == 'profession':
            ''' Ask about their profession '''
            profession = self.profession
            if profession is None:
                profession = 'No profession'

            asker.creature.add_person_fact_knowledge(other_person=self.owner, info_type=question_type, info=profession)

            return 'truth'

        elif question_type == 'events':
            return 'truth'

        elif question_type == 'battles':
            return 'truth'

        elif question_type == 'sites':
            return 'truth'

        elif question_type == 'age':
            ''' Ask about their profession '''
            age = self.get_age()

            asker.creature.add_person_fact_knowledge(other_person=self.owner, info_type=question_type, info=age)
            return 'truth'

        elif question_type == 'city':
            ''' Ask about the city they live in '''

            current_citizen_of = self.current_citizenship
            if current_citizen_of is None:
                current_citizen_of = 'No citizenship'

            asker.creature.add_person_fact_knowledge(other_person=self.owner, info_type=question_type, info=current_citizen_of)

            return 'truth'

        elif question_type == 'goals':
            ''' Ask about their goals '''

            goals = []
            if len(self.goals):
                for goal in self.goals:
                    goals.append(goal)

            asker.creature.add_person_fact_knowledge(other_person=self.owner, info_type=question_type, info=goals)

            return 'truth'

        elif question_type == 'recruit':
            ''' Try to recruit person into actor's party '''
            if self.get_age() >= g.MIN_MARRIAGE_AGE and (self.sex == 1 or self.spouse is None) \
                and self.profession is None and not self.commander:
                return 'yes'

            else:
                return 'no'

        else:
            return 'truth'


    def handle_pending_conversations(self):
        for (asker, question_type) in self.pending_conversations:

            #if self.owner == g.player:
                ## TODO - prompt GUI for g.player to choose his answer
            #    answer_type = self.determine_response(asker, question_type)
            #    self.verbalize_answer(asker, question_type, answer_type)
            #else:

            answer_type = self.determine_response(asker, question_type)
            self.verbalize_answer(asker, question_type, answer_type)

            # GUI stuff - must update when NPC gives response
            if asker == g.player:
                for panel in g.game.interface.get_panels(panel_name='talk_screen'):
                    panel.button_refresh_func(*panel.button_refresh_args)


        self.pending_conversations = []

    #def score_question(self, conversation, asker, target, question_type):
    #    score = 5
    #    return score

    def say(self, text_string):
        msg_color = libtcod.color_lerp(self.owner.color, g.PANEL_FRONT, .5)

        g.game.add_message('{0}: {1}'.format(self.owner.fullname(use_you=1), text_string), msg_color)

    def nonverbal_behavior(self, behavior, msg_color=None):
        ''' Any nonverbal behavior that this creature can undertake '''
        if g.game.map_scale == 'human':
            if msg_color is None:
                msg_color = libtcod.color_lerp(self.owner.color, g.PANEL_FRONT, .5)

            g.game.add_message('%s %s.' % (self.owner.fullname(use_you=1), behavior), msg_color)

    def verbalize_pain(self, damage, sharpness, pain_ratio):
        ''' The creature will verbalize its pain '''
        # Damage/pain ratio are decimals, so divide and multiply are opposite
        pain_composite = (damage * 3) + (pain_ratio / 2)
        will_verbalize = roll(1, 100) <= (pain_composite * 100)
        #will_verbalize = 1

        if will_verbalize:
            if pain_composite > .8:
                self.nonverbal_behavior('lets loose a bloodcurdling scream')
            elif pain_composite > .7:
                self.nonverbal_behavior('lets loose a shrill scream')
            elif pain_composite > .6:
                self.nonverbal_behavior('screams in pain')
            elif pain_composite > .5:
                self.nonverbal_behavior('screams')
            elif pain_composite > .4:
                self.nonverbal_behavior('grunts loudly')
            elif pain_composite > .3:
                self.nonverbal_behavior('grunts')

    def take_captive(self, figure):
        figure.creature.captor = self.owner
        self.captives.append(figure)

    def is_captive(self):
        ''' Function simply returns whether or not this guy is a captive '''
        return self.captor is not None

    def sapient_free_from_captivity(self):
        ''' Handles setting a sapient free from captivity, and making sure any army holding it captive is also properly handled '''
        self.captor.creature.captives.remove(self.owner)
        self.captor = None

        # Unsure if this will work properly, but, once freed, all creatures should re-evaluate to make sure captives show up as enemies properly
        for figure in g.M.creatures:
            if figure.local_brain:
                figure.local_brain.set_enemy_perceptions_from_cached_factions()
        ############################################################

        self.say('I\'m free!')

    def get_minor_successor(self):
        ''' A way for minor figures to pass down their profession, in cases where it's not a huge deal'''
        possible_successors = [child for child in self.children if child.creature.sex == 1 and child.creature.get_age() >= g.MIN_MARRIAGE_AGE]
        if possible_successors != []:
            return possible_successors[0]
        else:
            born = g.WORLD.time_cycle.years_ago(roll(18, 35))
            return self.current_citizenship.create_inhabitant(sex=1, born=born, dynasty=None, important=self.important)


    def die(self, reason):
        figure = self.owner
        successor = None

        self.set_status('dead')

        # Remove from the list of all figures, and the important ones if we're important
        if figure in g.WORLD.all_figures:
            g.WORLD.all_figures.remove(figure)
            g.WORLD.tiles[figure.wx][figure.wy].entities.remove(figure)


            # The faction lead passes on, if we lead a faction
            if self.faction and figure == self.faction.leader:
                self.faction.standard_succession()
            # Only check profession if we didn't have a title, so profession associated with title doesn't get weird
            elif self.profession:
                # Find who will take over all our stuff
                successor = self.get_minor_successor()
                self.profession.give_profession_to(successor)

            if self.current_citizenship:
                self.current_citizenship.entities_living_here.remove(figure)

            if self.faction:
                self.faction.remove_member(figure)

            event = hist.Death(date=g.WORLD.time_cycle.get_current_date(), location=(self.owner.wx, self.owner.wy), figure=figure, reason=reason)
            g.game.add_message(event.describe(), libtcod.red)

        elif g.game.map_scale == 'human' and player in g.M.sapients:
            location = g.WORLD.tiles[figure.wx][figure.wy].get_location_description()
            g.game.add_message('{0} has died in {1} due to {2}!'.format(figure.fulltitle(), location, reason), libtcod.red)

        if figure in g.WORLD.important_figures:
            g.WORLD.important_figures.remove(figure)


        ## If we were set to inherit anything, that gets updated now
        for faction, position in self.inheritance.iteritems():
            heirs = faction.get_heirs(3) # Should ignore us now since we're dead
            # If our position was 1st in line, let the world know who is now first in line
            if position == 1 and heirs != []:
                g.game.add_message('After the death of {0}, {1} is now the heir of {2}.'.format(figure.fulltitle(), heirs[0].fullname(), faction.name), libtcod.light_blue)
            elif position == 1:
                g.game.add_message('After the death of {0}, no heirs to {1} remiain'.format(figure.fulltitle(), faction.name), libtcod.light_blue)

        # Remove self from any armies we might be in
        if self.commander:
            if self in self.commander.creature.commanded_figures:
                self.commander.remove_commanded_figure(figure)

        # Handle successor to economy
        if self.economy_agent and successor:
            self.economy_agent.update_holder(successor)
            #g.game.add_message(successor.fulltitle() + ' is now ' + successor.sapient.economy_agent.name, libtcod.light_green)

        if self.house:
            self.house.remove_inhabitant(figure)


        ### Handle map stuff
        if g.game.map_scale == 'human':
            # Drop any things we have
            for component in self.get_graspers():
                if component.grasped_item is not None:
                    # Drop the object (and release hold on it)
                    self.owner.drop_object(own_component=component, obj=component.grasped_item)

            g.M.creatures.remove(figure)
            g.M.objects.append(figure)
            libtcod.map_set_properties(g.M.fov_map, figure.x, figure.y, True, True)

        # Object properties
        self.owner.set_display_color(self.owner.death_color)
        self.owner.blocks_mov = False
        self.owner.local_brain = None
        self.owner.name = 'Corpse of {0}'.format(self.owner.fulltitle())


    def get_age(self):
        return g.WORLD.time_cycle.date_dif(earlier_date=self.born, later_date=g.WORLD.time_cycle.get_current_date())

    def get_profession(self):
        if self.profession:
            return self.profession.name
        elif self.get_age() < g.MIN_CHILDBEARING_AGE:
            return 'Child'
        elif self.sex == 0 and self.spouse:
            return 'Housewife'
        elif self.sex == 0:
            return 'Maiden'
        return 'No profession'

    def take_spouse(self, spouse, date='today'):
        self.spouse = spouse
        spouse.creature.spouse = self.owner

        # Update infamy
        self.owner.infamy += int(spouse.infamy/2)
        spouse.infamy += int(self.owner.infamy/2)

        if date == 'today':
            date = g.WORLD.time_cycle.get_current_date()

        event = hist.Marriage(date=date, location=(self.owner.wy, self.owner.wy), figures=[self.owner, spouse])
        g.game.add_message(event.describe(), libtcod.color_lerp(g.PANEL_FRONT, self.owner.color, .3))

    def have_child(self, date_born='today'):

        if date_born == 'today':
            date_born = g.WORLD.time_cycle.get_current_date()

        child = self.culture.create_being(sex=roll(0, 1), born=date_born, dynasty=self.spouse.creature.dynasty,
                                          important=self.important, faction=self.faction, wx=self.owner.wx, wy=self.owner.wy, race=self.type_, save_being=1)

        # Let the child know who its siblings are
        for other_child in self.children:
            child.creature.siblings.append(other_child)
            # Update knowledge of child
            other_child.creature.meet(child)

        child.creature.mother = self.owner
        child.creature.father = self.spouse

        infamy_amount = int(child.creature.mother.infamy/2) + int(child.creature.father.infamy/2)
        child.add_infamy(amount=infamy_amount)

        # Add to children and update mother/father
        for parent in [self.owner, self.spouse]:
            parent.creature.children.append(child)
            parent.creature.meet(child)

        child.creature.generation = self.spouse.creature.generation + 1

        if self.current_citizenship:
            self.current_citizenship.add_citizen(child)

        event = hist. Birth(date=date_born, location=(self.owner.wx, self.owner.wy), parents=[self.owner, self.spouse], child=child)
        g.game.add_message(event.describe(), libtcod.color_lerp(g.PANEL_FRONT, self.owner.color, .3))

        return child

    def set_initial_traits(self):
        ## Give the person a few traits
        trait_num = roll(3, 4)
        while trait_num > 0:
            trait = random.choice(TRAITS)

            usable = 1
            for otrait in self.traits:
                if trait in TRAIT_INFO[otrait]['opposed_traits'] or trait == otrait:
                    usable = 0
                    break
            if usable:
                # "Somewhat = .5, regular = 1, "very" = 2
                multiplier = random.choice((.5, .5, 1, 1, 1, 1, 2))
                self.traits[trait] = multiplier
                trait_num -= 1

    def set_opinions(self):
        # Set opinions on various things according to our profession and personality
        self.opinions = {}

        for issue in g.PROF_OPINIONS:
            prof_opinion = 0
            personal_opinion = 0
            reasons = {}

            ## Based on profession ##
            if self.profession is not None and self.profession.category in g.PROF_OPINIONS[issue]:
                prof_opinion = g.PROF_OPINIONS[issue][self.profession.category]
                reasons['profession'] = prof_opinion

            ## Based on personal traits ##
            for trait, multiplier in self.traits.iteritems():
                if trait in g.PERSONAL_OPINIONS[issue]:
                    amount = g.PERSONAL_OPINIONS[issue][trait] * multiplier
                    reasons[trait] = amount
                    personal_opinion += amount

            # A total tally of the opinion
            opinion = prof_opinion + personal_opinion
            # Now we save the issue, our opinion, and the reasoning
            self.opinions[issue] = [opinion, reasons]


    def add_person_fact_knowledge(self, other_person, info_type, info):
        ''' Checks whether we know of the person and then updates info '''
        if not other_person in self.knowledge['entities']:
            self.add_awareness_of_person(other_person)

        self.knowledge['entities'][other_person]['stats'][info_type] = info

    def add_person_location_knowledge(self, other_person, date_learned, date_at_loc, location, heading, source):
        ''' Updates knowledge of the last time we learned about the location of the other '''
        self.knowledge['entities'][other_person]['location']['coords'] = location
        self.knowledge['entities'][other_person]['location']['date_learned'] = date_learned
        self.knowledge['entities'][other_person]['location']['date_at_loc'] = date_at_loc
        self.knowledge['entities'][other_person]['location']['source'] = source
        self.knowledge['entities'][other_person]['location']['heading'] = heading
        #self.knowledge['entities'][other_person]['location']['destination'] = destination

    def update_meeting_info(self, other, date):
        ''' Updates knowledge of the last time we met the other '''
        if self.knowledge['entities'][other]['meetings']['date_met'] is not None:
            self.knowledge['entities'][other]['meetings'] = {'date_met': date, 'date_of_last_meeting': date, 'number_of_meetings': 1}
        else:
            self.knowledge['entities'][other]['meetings']['date_of_last_meeting'] = date
            self.knowledge['entities'][other]['meetings']['number_of_meetings'] += 1


    def encounter(self, other):
        ''' Encounter another entity, updating knowledge as necessary '''
        date = g.WORLD.time_cycle.get_current_date()

        if not other in self.knowledge['entities']:
            self.add_awareness_of_person(other)

        self.add_person_location_knowledge(other_person=other, date_learned=date, date_at_loc=date, location=(self.owner.wx, self.owner.wy), heading=other.world_last_dir, source=self.owner)
        self.update_meeting_info(other, date)

        for event_id in self.knowledge['events']:
            # Only share events that are important. TODO - also share events pertaining to loved ones, even if they're not important
            if hist.historical_events[event_id].get_importance() >= 50:
                other.creature.add_knowledge_of_event(event_id=event_id, date_learned=date, source=self.owner)


    def add_knowledge_of_event(self, event_id, date_learned, source, location_accuracy=1):
        # Only trigger if we don't already know about the event
        if event_id not in self.knowledge['events']:
            self.knowledge['events'][event_id] = {'description': {}, 'location': {} }

            self.knowledge['events'][event_id]['description']['date_learned'] = date_learned
            self.knowledge['events'][event_id]['description']['source'] = source

            self.knowledge['events'][event_id]['location']['accuracy'] = location_accuracy
            self.knowledge['events'][event_id]['location']['date_learned'] = date_learned
            self.knowledge['events'][event_id]['location']['source'] = source

            #print 'On', date_learned, ', ', self.owner.fullname(), 'has learned', hist.historical_events[event_id].describe()

    def add_knowledge_of_event_location(self, event_id, date_learned, source, location_accuracy):
        '''location_accuracy: Scale of 1 to 5, where 5 is knowledge of the exact location '''
        # Only trigger if we don't already know the location of the event
        if self.knowledge['events'][event_id]['location']['accuracy'] < location_accuracy:
            self.knowledge['events'][event_id]['location']['accuracy'] = location_accuracy
            self.knowledge['events'][event_id]['location']['date_learned'] = date_learned
            self.knowledge['events'][event_id]['location']['source'] = source

        # 5 means we know exact location
        if location_accuracy == 5:
            # With the knowledge of the event location comes the knowledge that those who participated in the event must have been there at that time
            for entity in hist.historical_events[event_id].get_entities():
                # If we know about the person, and the date of the event is
                if entity in self.knowledge['entities'] and self.knowledge['entities'][entity]['location']['date_at_loc'] < hist.historical_events[event_id].date:
                    self.add_person_location_knowledge(other_person=entity, date_learned=date_learned, date_at_loc=hist.historical_events[event_id].date,
                                                       location=hist.historical_events[event_id].location, heading=-1, source=source)

                ## If we haven't heard of the other person yet, we won't know much other than that they were there
                elif entity not in self.knowledge['entities']:
                    self.add_awareness_of_person(other_person=entity)
                    self.add_person_location_knowledge(other_person=entity, date_learned=date_learned, date_at_loc=hist.historical_events[event_id].date,
                                                       location=hist.historical_events[event_id].location, heading=-1, source=source)

            #g.game.add_message(' ~   ~~ {0} has learned that {1}    '.format(self.owner.fullname(), hist.historical_events[event_id].describe()))

    def get_knowledge_of_events(self, days_ago):
        today = g.WORLD.time_cycle.get_current_date()
        return [e_id for e_id in self.knowledge['events'] if g.WORLD.time_cycle.date_dif(earlier_date=hist.historical_events[e_id].date, later_date=today, mode='days') <= days_ago]

    def add_knowledge_of_site(self, site, date_learned, source, location_accuracy=1):
        if site not in self.knowledge['sites']:
            self.knowledge['sites'][site] = {'description': {}, 'location': {} }

            self.knowledge['sites'][site]['description']['date_learned'] = date_learned
            self.knowledge['sites'][site]['description']['source'] = source

            self.knowledge['sites'][site]['location']['accuracy'] = location_accuracy
            self.knowledge['sites'][site]['location']['date_learned'] = date_learned
            self.knowledge['sites'][site]['location']['source'] = source

    def add_knowledge_of_sites_on_move(self, sites):

        if sites:
            date = g.WORLD.time_cycle.get_current_date()
            for site in sites:
                if site not in self.knowledge['sites']:
                    self.add_knowledge_of_site(site=site, date_learned=date, source=self, location_accuracy=1)

            if self.owner == g.player:
                sites_by_type = Counter([s.type_ for s in sites])
                tmplist = sorted([(type_, num) for type_, num in sites_by_type.iteritems()], key=lambda x: x[1], reverse=True)
                tmp = join_list([ct(type_, num, True) for type_, num in tmplist])


                if len(sites) == 1 and sites[0].name:
                    msg = 'The {0} of {1} is here. '.format(sites[0].type_, sites[0].get_name())
                else:
                    msg = 'There {0} {1}{2} here. '.format(cj('is', tmplist[0][1]), qaunt(tmplist[0][1]), tmp)

                g.game.add_message(msg)
                # g.game.add_message('{0} has learned that {1} is located at {2}'.format(self.fullname(), site.get_name(), (site.x, site.y)))



    def get_relations(self, other_person):
        # set initial relationship with another person
        # Needs to be greatly expanded, and able to see reasons why
        reasons = {}

        for trait, multiplier in self.traits.iteritems():
            for otrait in other_person.creature.traits:
                if trait == otrait:
                    reasons['Both ' + trait] = 4 * multiplier
                    break
                elif trait in TRAIT_INFO[otrait]['opposed_traits']:
                    reasons[trait + ' vs ' + otrait] = -2 * multiplier
                    break

        # Things other than traits can modify this, must be stored in self.extra_relations
        # Basically merge this into the "reasons" dict
        if other_person in self.knowledge['entities']:
            for reason, amount in self.knowledge['entities'][other_person]['relations'].iteritems():
                reasons[reason] = amount

        return reasons


    def modify_relations(self, other_person, reason, amount):
        # Anything affecting relationship not covered by traits

        # Add them to relation list if not already there
        if not other_person in self.knowledge['entities']:
            self.add_awareness_of_person(other_person)

        # Then add the reason
        if not reason in self.knowledge['entities'][other_person]['relations']:
            self.knowledge['entities'][other_person]['relations'][reason] = amount
        else:
            self.knowledge['entities'][other_person]['relations'][reason] += amount

    def add_awareness_of_person(self, other_person):
        ''' To set up the knowledge dict '''
        # Meeting info will be updated if / when we meet the other
        self.knowledge['entities'][other_person] = {}

        self.knowledge['entities'][other_person]['meetings'] = {'date_met': None, 'date_of_last_meeting': None, 'number_of_meetings': 0}
        self.knowledge['entities'][other_person]['relations'] = {}
        self.knowledge['entities'][other_person]['location'] = {'coords': None, 'date_learned': None, 'date_at_loc': None, 'source': None, 'heading': None}
        self.knowledge['entities'][other_person]['stats'] = {'profession': None, 'age': None, 'city': None, 'goals': None}

    def meet(self, other):
        # Use to set recipricol relations with another person
        self.modify_relations(other, 'Knows personally', 2)
        self.encounter(other)

        other.creature.modify_relations(self.owner, 'Knows personally', 2)
        other.creature.encounter(self.owner)


class DijmapSapient:
    ''' AI using summed dij maps '''
    def __init__(self):
        self.astar_refresh_period = 7
        self.ai_initialize()

        self.ai_state = 'idle'  # Should go here - moving temporarily
        self.current_action = None

        self.astar_refresh_cur = roll(1, 5)
        #
        self.target_figure = None
        self.target_location = None

        self.perceived_enemies = {}
        ## Create a list of all enemies we have not perceived yet
        self.unperceived_enemies = []
        self.perception_info = {'closest_enemy':None, 'closest_enemy_distance':None}

        # An ordered list of behaviors
        #self.behaviors = []

        self.patrol_route = []  # Should go here - moving temporarily
        self.current_patrol_index = 0
        self.follow_distance = 10

    def ai_initialize(self):
        self.ai_state = 'idle'  # Should go here - moving temporarily
        self.current_action = None

        self.astar_refresh_cur = roll(1, 5)
        #
        self.target_figure = None
        self.target_location = None

        self.perceived_enemies = {}
        ## Create a list of all enemies we have not perceived yet
        self.unperceived_enemies = []
        self.perception_info = {'closest_enemy':None, 'closest_enemy_distance':None}

        # An ordered list of behaviors
        #self.behaviors = []

        self.patrol_route = []  # Should go here - moving temporarily
        self.current_patrol_index = 0
        self.follow_distance = 10


    def set_enemy_perceptions_from_cached_factions(self):
        ''' Make sure We are not a captive (later, if freed, captives will need to run this routine) '''
        if not self.owner.creature.is_captive():

            for faction, members in g.M.factions_on_map.iteritems():
                #g.game.add_message('{0}'.format(faction.name), faction.color)

                if self.owner.creature.faction.is_hostile_to(faction):
                    #g.game.add_message('{0} hostile to {1}'.format(self.owner.creature.faction.name, faction), self.owner.creature.faction.color)

                    for member in members:
                        if member not in self.perceived_enemies and member not in self.unperceived_enemies and not member.creature.is_captive():
                            self.unperceived_enemies.append(member)
                            #g.game.add_message(new_msg="{0} adding {1} to enemies".format(self.owner.fullname(), member.fullname()), color=self.owner.color)

            #for enemy_faction in self.owner.creature.enemy_factions:
            #    for member in g.M.factions_on_map[enemy_faction]:
            #        if member not in self.perceived_enemies.keys() and member not in self.unperceived_enemies and not member.creature.is_captive():
            #            self.unperceived_enemies.append(member)


    def take_turn(self):
        # Can't do anything if we're unconscious or dead
        if self.owner.creature.is_available_to_act():
            self.perceive_surroundings()
            self.battle_behavior()
            #self.non_battle_behavior()

    def perceive_surroundings(self):
        actor = self.owner

        for figure in self.unperceived_enemies[:]:
            perceived, threat_level = actor.creature.check_to_perceive(figure)

            if perceived:
                #self.owner.creature.say('I see you, %s'%figure.fullname())
                self.perceived_enemies[figure] = threat_level
                self.unperceived_enemies.remove(figure)

        self.find_closest_perceived_enemy()

    def find_closest_perceived_enemy(self):

        closest_enemy = None
        closest_dist = 1000

        for figure in filter(lambda figure: figure.creature.is_available_to_act(), self.perceived_enemies):
            dist = self.owner.distance_to(figure)
            if dist < closest_dist:
                closest_enemy = figure
                closest_dist = dist

        ## Update perception dict
        self.perception_info['closest_enemy'] = closest_enemy
        self.perception_info['closest_enemy_dist'] = closest_dist


    def handle_astar_refresh(self):
        # Every 5 turns astar will refresh. Allows us to cache longer paths
        self.astar_refresh_cur -= 1
        if self.astar_refresh_cur == 0:
            self.astar_refresh_cur = self.astar_refresh_period
        # Clear dead targets
        if self.target_figure and not self.target_figure.creature.is_available_to_act():
            self.unset_target()
        # Refresh to new target location
        if self.target_figure and ( (1 <= len(self.owner.cached_astar_path) <= 5) or self.astar_refresh_cur == 5):
            self.target_location = (self.target_figure.x, self.target_figure.y)
            self.owner.set_astar_target(self.target_location[0], self.target_location[1], dbg_reason='has targ figure; 1 <= path len <= 5; refresh_cur = {0}'.format(self.astar_refresh_cur))
        # Path to target location if it exists and is not set
        elif not self.target_figure and self.target_location and not self.owner.cached_astar_path:
            self.owner.set_astar_target(self.target_location[0], self.target_location[1], dbg_reason='no targ figure / location / cached a* path')


    def set_target_figure(self, target_figure):
        self.target_figure = target_figure
        self.target_location = target_figure.x, target_figure.y
        ## Now set the location
        self.owner.set_astar_target(self.target_location[0], self.target_location[1], dbg_reason='set_target_figure()')

    def set_target_location(self, target_location):
        self.target_figure = None
        self.target_location = target_location
        self.owner.set_astar_target(self.target_location[0], self.target_location[1], dbg_reason='set_target_location()')

    def unset_target(self):
        self.target_figure = None
        self.target_location = None

    def astar_move(self):
        self.handle_astar_refresh()

        blocks_mov = self.owner.move_with_stored_astar_path(path=self.owner.cached_astar_path)

        if blocks_mov == 'path_end':
            g.game.add_message('%s reached end of path'%self.owner.fulltitle() )
            self.unset_target()

        elif blocks_mov == 1:
            # Reset path. TODO - new path to target_figure if exists
            self.owner.set_astar_target(self.target_location[0], self.target_location[1], dbg_reason='path was blocked - recalculating')
            self.owner.move_with_stored_astar_path(path=self.owner.cached_astar_path)

    def battle_behavior(self):
        actor = self.owner
        #has_moved = 0

        # Handle idle -> attacking behavior
        if self.ai_state not in ('fleeing', 'attacking') and self.perception_info['closest_enemy'] is not None:
            self.set_state('attacking')

        # Taking some extra perceptory info to understand when to flee
        if self.ai_state != 'fleeing' and ( (actor.creature.get_pain_ratio() > .5) or (actor.creature.blood < 5 and actor.creature.bleeding) ):
            self.set_state('fleeing')


        if self.ai_state == 'attacking':
            self.ai_state_attack()

        elif self.ai_state  == 'fleeing':
            self.ai_state_flee()

        elif self.ai_state == 'moving':
            self.ai_state_move()

        elif self.ai_state == 'following':
            self.ai_state_follow()

        elif self.ai_state == 'patrolling':
            self.ai_state_patrol()

        #if not has_moved:
        #    actor.creature.dijmap_move()

        # Finally, make any attacks which can be allowed
        if self.perception_info['closest_enemy'] is not None and self.perception_info['closest_enemy_dist'] < 2:
            self.attack_enemy(self.perception_info['closest_enemy'])



    def ai_state_attack(self):
        if self.perception_info['closest_enemy_dist'] < g.DIJMAP_CREATURE_DISTANCE:
            self.unset_target()
        # Use A* if enemy is out of certain distance
        if self.target_figure is None and self.perception_info['closest_enemy'] is not None and self.perception_info['closest_enemy_dist'] >= g.DIJMAP_CREATURE_DISTANCE:
            self.set_target_figure(target_figure=self.perception_info['closest_enemy'])

        # Use A* move
        if self.target_figure and self.perception_info['closest_enemy'] and self.perception_info['closest_enemy'] >= g.DIJMAP_CREATURE_DISTANCE:
            self.astar_move()

        else:
            self.owner.creature.dijmap_move()

    def ai_state_flee(self):
        actor = self.owner

        if not actor.creature.bleeding and actor.creature.get_pain_ratio() < .5:
            self.set_state('attacking')

        ## Hacking for now - using an abstract "bandage"
        elif actor.creature.bleeding and (self.perception_info['closest_enemy'] is None or self.perception_info['closest_enemy_dist'] > 8):
            actor.creature.bleeding = max(actor.creature.bleeding - .25, 0)
            g.game.add_message(actor.fullname() + ' has used a bandage', libtcod.dark_green)

        actor.creature.dijmap_move()


    def set_state(self, ai_state, **kwargs):
        actor = self.owner
        actor.creature.nonverbal_behavior(' is now %s'%ai_state )
        self.ai_state  = ai_state

        if self.ai_state  == 'attacking':
            # This will clear the target, in case they happen to be following someone or whatever
            self.unset_target()

            for faction in g.M.factions_on_map:
            #for faction in actor.creature.dijmap_desires.keys():
                if actor.creature.faction.is_hostile_to(faction):
                    actor.creature.dijmap_desires[faction.name] = 2

        elif self.ai_state  == 'fleeing':

            for faction in g.M.factions_on_map:
            #for faction in actor.creature.dijmap_desires.keys():
                if actor.creature.faction.is_hostile_to(faction):
                    actor.creature.dijmap_desires[faction.name] = -4

            actor.creature.dijmap_desires['map_center'] = -2

        elif self.ai_state == 'patrolling':
            if not self.patrol_route:
                self.patrol_route = kwargs['patrol_route']

        elif self.ai_state == 'moving':
            self.set_target_location(kwargs['target_location'])

        elif self.ai_state == 'following':
            self.set_target_figure(kwargs['target_figure'])


    def ai_state_patrol(self):
        ''' Handles route-setting and moving of patrolling entities '''
        if self.target_location is None:
            if g.M.get_astar_distance_to(x=self.owner.x, y=self.owner.y, target_x=self.patrol_route[self.current_patrol_index][0], target_y=self.patrol_route[self.current_patrol_index][1]) > 0:
                self.set_target_location(self.patrol_route[self.current_patrol_index])
            else:
                g.game.add_message('%s could not reach patrol route at (%i, %i), aborting' %(self.owner.fulltitle(), self.patrol_route[self.current_patrol_index][0], self.patrol_route[self.current_patrol_index][1]) )
                del self.patrol_route[self.current_patrol_index]
                self.set_target_location(self.patrol_route[self.current_patrol_index])

        if get_distance_to(self.owner.x, self.owner.y, self.target_location[0], self.target_location[1]) < 2:
            self.current_patrol_index = looped_increment(self.current_patrol_index, len(self.patrol_route)-1, 1)

            self.set_target_location(self.patrol_route[self.current_patrol_index])

        self.astar_move()


    def ai_state_move(self):
        if self.target_location:
            distance = get_distance_to(self.owner.x, self.owner.y, self.target_location[0], self.target_location[1])
            if self.target_location and distance > 0:
                self.astar_move()

            elif distance == 0:
                self.unset_target()
                self.set_state('idle')


    def ai_state_follow(self):
        if self.target_figure and self.owner.distance_to(self.target_figure) > self.follow_distance:
            self.astar_move()


    def attack_enemy(self, enemy):
        self.owner.creature.turns_since_move = 0
        # TODO - make sure this makeshift code is turned into something much more intelligent
        weapon = self.owner.creature.get_current_weapon()
        if weapon:
            opening_move = random.choice([m for m in combat.melee_armed_moves if m not in self.owner.creature.last_turn_moves])
            move2 = random.choice([m for m in combat.melee_armed_moves if m != opening_move and m not in self.owner.creature.last_turn_moves])
            self.owner.creature.set_combat_attack(target=enemy, opening_move=opening_move, move2=move2)


class BasicWorldBrain:
    def __init__(self):
        self.path = None
        self.next_tick = 0

        self.current_goal_path = []

    def find_cheapest_behavior_path(self, behavior_paths_costed):

        figure = self.owner
        current_lowest_cost, current_lowest_behavior_path = 100000, None
        all_costs = []
        for behavior_path, behavior_base_costs in behavior_paths_costed:
            # Each behavior path gets a running cost total
            total_cost = 0
            for cost_aspect, base_cost in behavior_base_costs.iteritems():
                # Go through each trait and see what that trait adds to the total cost
                cost_multiplier = 1
                for trait, trait_intensity in figure.creature.traits.iteritems():
                    cost_multiplier *= TRAIT_INFO[trait]['behavior_modifiers'][cost_aspect]
                    #trait_cost_multiplier = TRAIT_INFO[trait]['behavior_modifiers'][cost_aspect]
                    #total_cost += (base_cost * trait_cost_multiplier)
                total_cost += (base_cost * cost_multiplier)

            if total_cost < current_lowest_cost:
                current_lowest_cost = total_cost
                current_lowest_behavior_path = behavior_path

            all_costs.append((behavior_path, total_cost))

        return current_lowest_behavior_path, current_lowest_cost, all_costs


    def set_goal(self, goal_state, reason, priority=1):

        behavior_paths_costed = goap.get_costed_behavior_paths(goal_state=goal_state, entity=self.owner)

        best_path, best_cost, all_costs = self.find_cheapest_behavior_path(behavior_paths_costed=behavior_paths_costed)

        #for path, cost in all_costs:
        #    print [b.behavior for b in path], cost

        if best_path:
            # Add to current goal list
            goap.set_behavior_parents(behavior_path=best_path)
            self.current_goal_path = best_path
            # print self.owner.fulltitle(), 'desiring to', goal_state.get_name(), ' -- behaviors:', join_list([b.get_name() for b in best_path])
        else:
            logging.warning("Goal paths: {0} had no best path to {1}".format(self.owner.fulltitle(), goal_state.get_name()) )


        return best_path

    def get_current_behavior(self):
        if self.current_goal_path:
            return self.current_goal_path[0].get_name()
        else:
            return 'No current goals'

    def get_final_behavior(self):
        if self.current_goal_path:
            return self.current_goal_path[-1].get_name()
        else:
            return 'No current goals'

    def take_goal_behavior(self):
        current_goal = self.current_goal_path[0]

        if not current_goal.activated:
            current_goal.activate()

        current_goal.take_behavior_action()

        if current_goal.is_completed():
            self.current_goal_path.remove(current_goal)


    def monthly_life_check(self):
        creature = self.owner.creature
        age = creature.get_age()

        if self.owner.creature.intelligence_level == 3:
            # Pick a spouse and get married immediately
            if creature.spouse is None and self.owner.creature.sex == 1 and g.MIN_MARRIAGE_AGE <= age <= g.MAX_MARRIAGE_AGE:
                if roll(1, 48) >= 48:
                    self.pick_spouse()

            # Have kids! Currenly limiting to 2 for non-important, 5 for important (will need to be fixed/more clear later)
            # Check female characters, and for now, a random chance they can have kids
            if creature.spouse and self.owner.creature.sex == 0 and g.MIN_CHILDBEARING_AGE <= age <= g.MAX_CHILDBEARING_AGE and len(creature.children) <= (creature.important * 3) + 2:
                if roll(1, 20) == 20:
                    creature.have_child()

            ####### Specal case - bards #######
            if self.owner.creature.profession and self.owner.creature.profession.name == 'Bard':
                target_city = random.choice([city for city in g.WORLD.cities if (city.x, city.y) != (self.owner.wx, self.owner.wy)])
                reason = 'travel from city to city to make my living!'
                goal_state = goap.IsHangingOut(target_location=(target_city.x, target_city.y), entity=self.owner, action='perform music')
                self.set_goal(goal_state=goal_state, reason=reason)


    def pick_spouse(self):
        ''' Pick someone to marry. Not very sophistocated for now. Must be in a site to consider marriage '''
        if g.WORLD.tiles[self.owner.wx][self.owner.wy].site:
            potential_spouses = [figure for figure in g.WORLD.tiles[self.owner.wx][self.owner.wy].entities
                                 if figure.creature.sex != self.owner.creature.sex
                                 and figure.creature.type_ == self.owner.creature.type_
                                 and figure.creature.dynasty != self.owner.creature.dynasty
                                 and g.MIN_MARRIAGE_AGE < figure.creature.get_age() < g.MAX_MARRIAGE_AGE]

            if len(potential_spouses) == 0 and self.owner.creature.current_citizenship:
                # Make a person out of thin air to marry
                sex = abs(self.owner.creature.sex-1)
                born = g.WORLD.time_cycle.years_ago(roll(18, 30))
                potential_spouses = [self.owner.creature.current_citizenship.create_inhabitant(sex=sex, born=born,
                                                                                dynasty=None, race=self.owner.creature.type_,
                                                                                important=self.owner.creature.important,
                                                                                house=self.owner.creature.house)]
            elif self.owner.creature.current_citizenship is None:
                g.game.add_message('{0} wanted to pick a spouse, but was not a citizen of any city'.format(self.owner.fulltitle()), libtcod.dark_red)
                return

            spouse = random.choice(potential_spouses)

            self.owner.creature.meet(spouse)

            self.owner.creature.take_spouse(spouse=spouse)
            ## Notify world
            # g.game.add_message(''.join([self.owner.fullname(), ' has married ', spouse.fullname(), ' in ', creature.current_citizenship.name]) )
            # Update last names
            if self.owner.creature.sex == 1:    spouse.creature.lastname = self.owner.creature.lastname
            else:                self.owner.creature.lastname = spouse.creature.lastname

            ## Move in
            if spouse.creature.current_citizenship != self.owner.creature.current_citizenship:
                #g.game.add_message('{0} (spouse), citizen of {1}, had to change citizenship to {2} in order to complete marriage'.format(spouse.fullname(), spouse.creature.current_citizenship.name, creature.current_citizenship.name ), libtcod.dark_red)
                self.owner.creature.current_citizenship.add_citizen(entity=spouse)

            return spouse

    def take_turn(self):
        ''' Covers taking a "turn" on the world map. This is run daily to resolve issues of pursuing goals. Larger decisions
            about what goals to pursue will likely be made elsewhere, run less frequently '''

        if self.owner.creature.is_available_to_act():
            ## Here will be the check for take goal behavior or re-evaluating goals
            if self.current_goal_path:
                self.take_goal_behavior()
            ## Otherwise, for now, some debug behaviors chosen at random.
            else:
                if self.owner.creature.intelligence_level == 3 and roll(1, 10) == 1:
                    unique_objs = [o for o in self.owner.creature.faction.unique_object_dict if 'weapon' in self.owner.creature.faction.unique_object_dict[o]['tags']]
                    item_name = random.choice(unique_objs) if unique_objs else 'shirt'

                    self.set_goal(goal_state=goap.HaveItem(item_name=item_name, entity=self.owner), reason='hehehehehe', priority=1)

                elif self.owner.creature.intelligence_level == 2 and roll(1, 100) == 1:
                    building = self.choose_building_to_live_in()
                    self.set_goal(goal_state=goap.HaveShelterInBuilding(entity=self.owner, building=building), reason='hehehehe', priority=1)

            # If we can threaten the economic output of a tile, flag any economic agents working that tile as unable to work
            if self.owner.creature.threatens_economic_output() and g.WORLD.tiles[wx][wy].territory and self.owner.creature.faction.is_hostile_to(g.WORLD.tiles[wx][wy].territory.faction):
                for resource, info in g.WORLD.tiles[wx][wy].region.agent_slots.iteritems():
                    for agent in info['agents']:
                        agent.activity_is_blocked = 1

            # Add to world's set of tiles which can potentially have encounters - later in the turn sequence, the game
            # will check these tiles and run the encounters as necessary. Only add tiles which aren't sites, and tiles
            # with more than 1 entity in it
            if (not g.WORLD.tiles[self.owner.wx][self.owner.wy].site) and len(g.WORLD.tiles[self.owner.wx][self.owner.wy].entities) > 1:
                g.WORLD.tiles_with_potential_encounters.add(g.WORLD.tiles[self.owner.wx][self.owner.wy])


    def choose_building_to_live_in(self):
        ''' Pick a building to move into '''

        ## TODO - make this work for regular people, not just bandits
        # Look at nearby buildings, pick one if empty, or construct a new one
        entity_region = g.WORLD.tiles[self.owner.wx][self.owner.wy]
        nearby_chunks = g.WORLD.get_nearby_chunks(chunk=entity_region.chunk, distance=3)

        # Find some nearby non-city non-village sites, and then find any empty buildings within these
        nearby_sites = [site for chunk in nearby_chunks for site in chunk.get_all_sites() if site.type_ not in ('city', 'village')]
        nearby_empty_buildings = [building for site in nearby_sites for building in site.buildings if not building.inhabitants]

        # If there are nearby empty buildings, choose one at random
        if nearby_empty_buildings and roll(0, 1):
            building = random.choice(nearby_empty_buildings)
        # If not, make a building object to send to the parent (but this doesn't actually exist yet - it will be added to a site later)
        else:
            # Choose a site for the building
            site = Site(world=g.WORLD, type_='hideout', x=self.owner.wx, y=self.owner.wy, char=g.HIDEOUT_TILE, name='test site', color=libtcod.red)

            building = building_info.Building(zone='residential', type_='hideout', template='TEST', construction_material='stone cons materials',
                                              site=site, professions=[], inhabitants=[], tax_status='commoner', wx=None, wy=None, constructed=0)

        return building

    '''
    def make_decision(self, decision_name):
        weighed_options = {}
        for option in decisions[decision_name]:
            weighed_options[option] = {}

            if self.owner.creature.profession and self.owner.creature.profession.name in option['professions']:
                weighed_options[option][self.owner.creature.profession.name] = decisions[decision_name][option][self.owner.creature.profession.name]

            for trait in option['traits']:
                if trait in self.owner.creature.traits:
                    weighed_options[option][trait] = decisions[decision_name][trait]

            for misc_reason in option['misc']:
                weighed_options[option][misc_reason] = decisions[decision_name][option][misc_reason]
    '''

class TimeCycle(object):
    ''' Code adapted from Paradox Inversion on libtcod forums '''
    def __init__(self, world):
        self.world = world
        self.ticks_per_hour = 600
        self.hours_per_day = 24
        self.days_per_week = 7
        self.days_per_month = 30
        self.months_per_year = 12

        self.current_day_tick = 0
        self.current_tick = 0
        self.current_hour = 0
        self.current_day = 0
        self.current_weekday = 0
        self.current_month = 0
        self.current_year = 1

        self.weekdays = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
        self.months = ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December')

        ## Dict of events, with keys being the future Y, M, and D, and values being a list of events
        self.events = defaultdict(list)

    def get_future_date(self, days_in_advance):
        (years, months, days_left) = self.days_to_date(days_in_advance)

        total_days = self.current_day + days_left
        if total_days <= self.days_per_month:
            future_day = total_days
        else:
            future_day = total_days - self.days_per_month
            months += 1 #should never be more than 1 month

        total_months = self.current_month + months
        if total_months <= self.months_per_year:
            future_month = total_months
        else:
            future_month = total_months - self.months_per_year
            years += 1 #should never be more than 1 year

        future_year = self.current_year + years

        return (future_year, future_month, future_day)

    def days_to_date(self, number_of_days):
        ''' Convert # of days to a (years, months, days) tuple '''
        (years, remainder) = divmod(number_of_days, (self.months_per_year * self.days_per_month))
        (months, days_left) = divmod(remainder, self.days_per_month)

        return (years, months, days_left)

    def add_event(self, date, event):
        ''' Should add an event to the scheduler'''
        (year, month, day) = date
        self.events[(year, month, day)].append(event)

    def handle_events(self):
        if (self.current_year, self.current_month, self.current_day) in self.events:
            for event in self.events[(self.current_year, self.current_month, self.current_day)]:
                event()

    def check_tick(self):
        if self.current_tick == self.ticks_per_hour:
            self.current_tick = 0
            self.current_hour += 1
            self.check_hour()

    def check_hour(self):
        # If it's 7am, day breaks
        if self.current_hour == 7:
                self.nightToDay()
        # If it's 7pm, night falls
        elif self.current_hour == 19:
                self.dayToNight()

        if self.current_hour == self.hours_per_day + 1:
            self.current_hour = 0
            self.current_day += 1
            self.current_weekday += 1
            self.check_day()

            self.day_tick()

    def next_day(self):
        if self.current_day + 1 >= self.days_per_month:
            next_day = 0
        else:
            next_day = self.current_day + 1
        return next_day

    def check_day(self):
        # Day to day stuff
        self.current_day += 1
        self.current_weekday += 1

        # Change week (civs take turn)
        if self.current_weekday == self.days_per_week:
            self.current_weekday = 0
            self.week_tick()

        # Change month
        if self.current_day == self.days_per_month:
            self.current_day = 0
            self.month_tick()

    def check_month(self):
        if self.current_month == self.months_per_year:
            self.year_tick()

    def goto_next_week(self):
        days_til_next_week = self.days_per_week - self.current_weekday
        for i in xrange(days_til_next_week):
            self.day_tick()

    def dayToNight(self):
        pass

    def nightToDay(self):
        pass

    def get_current_date(self):
        return (self.current_year, self.current_month, self.current_day)

    def date_dif(self, earlier_date, later_date, mode='years'):
        years1, months1, days1 = earlier_date
        years2, months2, days2 = later_date

        days_dif = ((years2 * self.days_per_month * self.months_per_year) + (months2 * self.days_per_month) + days2 ) - \
                   ((years1 * self.days_per_month * self.months_per_year) + (months1 * self.days_per_month) + days1 )

        if mode == 'years':
            return int(days_dif / (self.days_per_month * self.months_per_year) )
        elif mode == 'months':
            return int(days_dif / self.days_per_month)
        elif mode == 'days':
            return days_dif
        elif mode == 'date_format':
            return self.days_to_date(days_dif)

    #def get_current_date_as_text(self):
    #    return '{0}, {1} {2}'.format(self.weekdays[self.current_weekday], self.months[self.current_month], self.current_day + 1)

    def date_to_text(self, date):
        year, month, day = date
        return '{0} {1}, {2}'.format(self.months[month], day + 1, year)

    def get_current_time(self):
        minutes = int(math.floor(self.current_tick / 10))
        if minutes < 10:
            minutes = '0{0}'.format(minutes)
        else:
            minutes = str(minutes)

        return '{0}:{1}'.format(self.current_hour, minutes)

    def years_ago(self, years, randomize=1):
        year = self.current_year - years

        if randomize:
            return (year, roll(0, self.months_per_year - 1), roll(0, self.days_per_month - 1))
        else:
            return (year, self.current_month, self.current_day)

    #a tick method, which was implemented before libtcod. it now keeps track of how many turns have passed.
    def tick(self):
        self.current_tick += 1
        self.check_tick()

        ### Creatures
        for creature in g.M.creatures:
            creature.creature.handle_tick()

            if creature.local_brain and creature.creature.next_tick <= self.current_tick:
                next_tick = creature.creature.next_tick + creature.creature.attributes['movespeed']
                if next_tick >= self.ticks_per_hour:
                    next_tick = next_tick - self.ticks_per_hour
                creature.creature.next_tick = next_tick
                creature.local_brain.take_turn()

        ### Sapients
        for actor in g.M.creatures:
            # Talk
            actor.creature.handle_pending_conversations()
            # Bleed every tick, if necessary
            actor.creature.handle_tick()

            #if actor.ai and actor.creature.next_tick == self.current_tick:
            if actor.local_brain and actor.creature.next_tick <= self.current_tick:
                next_tick = actor.creature.next_tick + actor.creature.attributes['movespeed']
                if next_tick >= self.ticks_per_hour:
                    next_tick = next_tick - self.ticks_per_hour
                actor.creature.next_tick = next_tick
                actor.local_brain.take_turn()

        # Now that entities have made their moves, calculate the outcome of any combats
        combat.handle_combat_round(actors=g.M.creatures)

        g.M.update_dmaps()


    def day_tick(self):
        ''' All the events that happen each day in the world '''
        self.check_day()
        self.handle_events()

        # Each day, random people in cities can encounter one another to spread knowledge
        for city in g.WORLD.cities:
            city.run_random_encounter()

        # Then, all entities in the world can take their daily turn
        for figure in reversed(g.WORLD.all_figures):
            if figure.world_brain: #and figure .world_brain.next_tick == self.current_day:
                #figure.world_brain.next_tick = self.next_day()
                figure.world_brain.take_turn()

        g.WORLD.check_for_encounters()



    def week_tick(self):
        begin = time.time()
        # Cheaply defined to get civs working per-day
        for city in self.world.cities:
            city.econ.run_simulation()
        g.game.add_message('econ run in {0:.2f} seconds'.format(time.time() - begin))

        for city in self.world.cities:
            city.dispatch_caravans()


        # Player econ preview - to show items we're gonna bid on
        if g.game.state == 'playing' and g.player.creature.economy_agent:
            g.player.creature.economy_agent.player_auto_manage()
            panel4.tiles_dynamic_buttons = []
            panel4.recalculate_wmap_dyn_buttons = True

        elif g.game.state == 'playing' and panel4.render:
            panel4.render = 0


    def month_tick(self):
        self.current_month += 1
        self.check_month()

        ## Have figures do some stuff monthly
        for figure in g.WORLD.all_figures[:]:
            ## TODO - make sure this check works out all the time
            if figure.creature.is_available_to_act():
                figure.world_brain.monthly_life_check()


    def year_tick(self):
        self.current_month = 0
        self.current_year += 1
        #g.game.add_message('It is now ' + str(self.current_year), libtcod.light_sea)
        for figure in g.WORLD.all_figures[:]:
            # Die from old age
            if figure.creature.get_age() > phys.creature_dict[figure.creature.type_]['creature']['lifespan']:
                figure.creature.die(reason='old age')

    def rapid_tick(self, ticks):
        ticks = ticks
        for x in xrange(ticks):
            self.tick()

    def rapid_hour_tick(self, hours):
        for x in xrange(hours):
            self.hour_tick()

    def rapid_month_tick(self, months):
        for x in xrange(months):
            self.month_tick()

class Camera:
    def __init__(self, width_in_characters, height):
        self.width_in_characters = width_in_characters
        self.height = height

        self.x = 0
        self.y = 0

        self.scalemap = {'world': g.WORLD, 'human': g.M}

    def get_xy_for_rendering(self):
        ''' Will get the xy points of the camera, skipping every second  '''
        for y in xrange(self.height):
            for x in xrange(0, self.width_in_characters, 2):
                mx, my = self.cam2map(x, y)
                yield (x, y, mx, my)

    def move_in_direction(self, dx, dy):
        ''' Moves the camera in a direction '''
        if dx or dy:
            # Set the target x and y values, to be modified by the direction
            target_x, target_y = self.x, self.y

            if g.game.map_scale == 'world':
                # Make sure the new camera coordinate won't let the camera see off the map
                if 0 <= self.x + dx < (g.WORLD.width * 2) - self.width_in_characters:   target_x += dx
                if 0 <= self.y + dy < g.WORLD.height - self.height:                     target_y += dy

            if g.game.map_scale == 'human':
                # Make sure the new camera coordinate won't let the camera see off the map
                if 0 <= self.x + dx <= (g.M.width * 2) - self.width_in_characters:  target_x += dx
                if 0 <= self.y + dy <= g.M.height - self.height:                    target_y += dy


            # if g.WORLD.is_val_xy((target_x, target_y)):
            #     # Actually perform the move
            self.move_to_location(target_x, target_y)


    def move_to_location(self, x, y):
        ''' Move camera to a target location '''
        # Ensure camera X is always even, to prevent some issues from arising no that
        # each "tile" is two characters wide.
        if x % 2 != 0:
            x -= 1

        self.x, self.y = x, y


    def center(self, target_x, target_y):
        #new camera coordinates (top-left corner of the screen relative to the map)
        x = (target_x * 2) - int(round(self.width_in_characters / 2)) #coordinates so that the target is at the center of the screen
        y = target_y - int(round(self.height / 2))

        #make sure the camera doesn't see outside the map
        x, y = max(0, x), max(0, y)

        if g.game.map_scale == 'world':
            if x > (g.WORLD.width * 2) - self.width_in_characters:
                x = (g.WORLD.width * 2) - self.width_in_characters
            if y > g.WORLD.height - self.height:
                y = g.WORLD.height - self.height

        ## Add FOV compute once it works for the world.
        elif g.game.map_scale == 'human':
            if x > (g.M.width * 2) - self.width_in_characters:
                x = (g.M.width * 2) - self.width_in_characters
            if y > g.M.height - self.height:
                y = g.M.height - self.height

        # Actually perform the move
        self.move_to_location(x, y)

    def map2cam(self, x, y):
        ''' 'convert coordinates on the map to coordinates on the screen '''

        # Awful hack to account for camera "moving" when it actually doesn't (due to 2 characters per "tile")
        adjusted_x = self.x if self.x % 2 == 0 else self.x - 1

        (x, y) = ((x*2) - adjusted_x, y - self.y)
        return (x, y)

    def cam2map(self, x, y):
        ''' convert coordinates on the screen to coordinates on the map '''
        (x, y) = (int((x + self.x) * .5), y + self.y)
        return (x, y)

    def click_and_drag(self, mouse):
        ''' Handles clicking and dragging to move map around, on both scale-level maps '''
        ox, oy = self.cam2map(mouse.cx, mouse.cy)

        momentum = 0
        while not mouse.lbutton_pressed:
            # Need to force game to update FOV while dragging if on human-scale map; otherwise map console will not update
            if g.game.map_scale == 'human':
                g.game.handle_fov_recompute()
            g.game.render_handler.render_all()

            event = libtcod.sys_check_for_event(libtcod.EVENT_KEY_PRESS | libtcod.EVENT_MOUSE, key, mouse)  #get mouse position and click status

            (x, y) = self.cam2map(mouse.cx, mouse.cy)

            dif_x, dif_y = (x - ox, y - oy)
            # add some momentum to the g.game.camera
            # if dif_x != ox and dif_y != oy:
            #     momentum += 2
            # else:
            #     momentum = max(momentum - 1, 0)

            self.move_in_direction(-dif_x, -dif_y)

        # after button is released, move the g.game.camera a bit more based on momentum
        # total_momentum = momentum
        # m_amt = 1
        # while momentum and int(round(dif_x * m_amt)) + int(round(dif_y * m_amt)):
        #     momentum -= 1
        #     m_amt = momentum / total_momentum
        #     # Need to force game to update FOV while dragging if on human-scale map; otherwise map console will not update
        #     if g.game.map_scale == 'human':
        #         g.game.handle_fov_recompute()
        #     g.game.render_handler.render_all()
        #
        #     self.move_in_direction(-int(round(dif_x * m_amt)), -int(round(dif_y * m_amt)))
        #
        #     # Remove any extra momentum on hitting map edge
        #     if g.game.map_scale == 'world':
        #         wx, wy = self.cam2map(x=self.x, y=self.y)
        #         if not (0 < wx < (g.WORLD.width * 2) - self.width_in_characters and 0 < wy < g.WORLD.height - self.height):
        #             momentum = 0
        #     elif g.game.map_scale == 'human':
        #         mx, my = self.cam2map(x=self.x, y=self.y)
        #         if not (0 < mx < (g.M.width * 2) - self.width_in_characters and 0 < my < g.M.height - self.height):
        #             momentum = 0

    def mouse_is_on_map(self):
        ''' Ensures mouse doesn't pick up activity outside edge of g.game.camera '''
        return (0 <= mouse.cx <= self.width_in_characters and 0 <= mouse.cy <= self.height)


class Culture:
    def __init__(self, color, language, world, races):
        self.color = color
        self.language = language
        self.name = self.gen_word(syllables=roll(1, 3), num_phonemes=(3, 20), cap=1)

        self.world = world
        self.races = races
        # Set astrology from the world
        self.astrology = religion.Astrology(world.moons, world.suns, language=self.language)
        self.pantheon = religion.Pantheon(astrology=self.astrology, num_nature_gods=roll(1, 2))

        self.subsistence = 'hunter-gatherer'
        self.c_knowledge = {
                            'sites': {},
                            'events': {},
                        }

        self.neighbor_cultures = []

        self.territory = []
        # "Center" of territory
        self.centroid = None

        self.villages = []
        self.access_res = []

        self.culture_traits = {}
        self.set_culture_traits()
        self.weapons = []

        # On initial run, it should only generate spears (and eventually bows)
        self.create_culture_weapons()

        # Is a list of (x, y) coords - used at beginning, when we're expanding
        self.edge = None

    def expand_culture_territory(self):
        ''' Once all cultures are created, they expand one turn at a time. This is the method called to expand '''
        newedge = []
        expanded = 0
        for (x, y) in self.edge:
            for (s, t) in get_border_tiles(x, y):
                if g.WORLD.is_val_xy((s, t)) and not g.WORLD.tiles[s][t].blocks_mov and not g.WORLD.tiles[s][t].culture:
                    expanded = 1
                    # A little randomness helps the cultures look more natural
                    # However, we must set expanded to true so that even if the check fails, this culture will
                    # go back to expand again next round (Fixes glitch where cultures stopped expanding before continent was filled)
                    if roll(1, 5) > 1:
                        self.add_territory(s, t)
                        newedge.append((s, t))
                    # If random roll fails, must re-check this tile
                    else:
                        newedge.append((x, y))

        self.edge = newedge

        return expanded

    def add_territory(self, x, y):
        g.WORLD.tiles[x][y].culture = self
        self.territory.append((x, y))


    def set_culture_traits(self):
        trait_num = roll(3, 4)
        while trait_num > 0:
            trait = random.choice(CULTURE_TRAIT_INFO.keys())

            for otrait in self.culture_traits:
                if trait in CULTURE_TRAIT_INFO[otrait]['opposed_traits'] or trait == otrait:
                    break
            else:
                # "Somewhat = .5, regular = 1, "very" = 2
                multiplier = random.choice([.5, .5, 1, 1, 1, 1, 2])
                self.culture_traits[trait] = multiplier
                trait_num -= 1

    def set_subsistence(self, subsistence):
        self.subsistence = subsistence


    def add_c_knowledge_of_site(self, site, location_accuracy=1):
        self.c_knowledge['sites'][site] = {'description': {}, 'location': {} }
        self.c_knowledge['sites'][site]['location']['accuracy'] = location_accuracy

    def transfer_c_knowledge_to_entity(self, entity, date):
        # print self.name, self.subsistence, self.c_knowledge['sites']
        for site in self.c_knowledge['sites']:
            accuracy = self.c_knowledge['sites'][site]['location']['accuracy']
            entity.creature.add_knowledge_of_site(site=site, date_learned=date, source=self, location_accuracy=accuracy)

    def setup_entity_knowledge(self, entity, date):
        ''' Make sure the entity starts with some knowledge '''
        self.transfer_c_knowledge_to_entity(entity=entity, date=date)

        if entity.wx and entity.wy and g.WORLD.tiles[entity.wx][entity.wy].site:
            entity.creature.add_knowledge_of_site(site=g.WORLD.tiles[entity.wx][entity.wy].site, date_learned=date, source=self, location_accuracy=1)

    def gen_word(self, syllables, num_phonemes=(3, 20), cap=0):
        word = self.language.gen_word(syllables=syllables, num_phonemes=num_phonemes)

        if cap:
            word = lang.spec_cap(word)

        return word

    def create_culture_weapons(self):
        ''' Culturally specific weapons '''
        # If we can't access resources, for now we can still make weapons out of wood
        if not ('iron' in self.access_res or 'bronze' in self.access_res or 'copper' in self.access_res):
            weapon_types = phys.basic_weapon_types
            materials = ['wood']
        else:
            weapon_types = phys.blueprint_dict.keys()
            materials = [m for m in self.access_res if m=='iron' or m=='bronze' or m=='copper']

        ''' Create a few types of unique weapons for this culture '''
        for wtype in weapon_types:
            material_name = random.choice(materials)
            material = data.commodity_manager.materials[material_name]

            special_properties = {random.choice(phys.PROPERTIES): random.choice( (5, 10) ) }

            # Send it over to the item generator to generate the weapon
            weapon_info_dict = phys.wgenerator.generate_weapon(wtype=wtype, material=material, special_properties=special_properties)

            weapon_name = self.gen_word(syllables=roll(1, 2))

            name = weapon_name + ' ' + wtype
            weapon_info_dict['name'] = name

            # Finally, append to list of object dicts
            #self.weapon_info_dicts.append(weapon_info_dict)
            self.weapons.append(name)

            phys.object_dict[name] = weapon_info_dict


    def add_villages(self):
        for x, y in self.territory:
            for resource in g.WORLD.tiles[x][y].res:
                if resource not in self.access_res and g.WORLD.is_valid_site(x, y, None, g.MIN_SITE_DIST) and not len(g.WORLD.tiles[x][y].minor_sites):
                    self.access_res.append(resource)
                    self.add_village(x, y)
                    break


    def add_village(self, x, y):
        name = lang.spec_cap(self.language.gen_word(syllables=roll(1, 2), num_phonemes=(2, 14)))
        village = Site(world=g.WORLD, type_='village', x=x, y=y, char=g.VILLAGE_TILE, name=name, color=self.color)
        g.WORLD.sites.append(village)

        g.WORLD.tiles[x][y].site = village
        g.WORLD.tiles[x][y].all_sites.append(village)

        g.WORLD.tiles[x][y].chunk.add_site(village)

        self.villages.append(village)



    def create_being(self, sex, born, dynasty, important, faction, wx, wy, armed=0, race=None, save_being=0, intelligence_level=3, char=None, world_char=None):
        ''' Create a human, using info loaded from xml in the physics module '''
        # If race=None then we'll need to pick a random race from this culture
        if not race:
            race = random.choice(self.races)

        # Look up the creature (imported as a dict with a million nested dicts
        info = phys.creature_dict[race]

        # Gen names based on culture and dynasty
        if sex == 1: firstname = lang.spec_cap(random.choice(self.language.vocab_m.values()))
        else:        firstname = lang.spec_cap(random.choice(self.language.vocab_f.values()))

        if dynasty is not None:   lastname = dynasty.lastname
        else:                     lastname = lang.spec_cap(random.choice(self.language.vocab_n.values()))

        # The creature component
        creature_component = Creature(type_=race, sex=sex, intelligence_level=intelligence_level, firstname=firstname, lastname=lastname, culture=self, born=born, dynasty=dynasty, important=important)


        human = assemble_object(object_blueprint=info, force_material=None, wx=wx, wy=wy, creature=creature_component,
                                local_brain=DijmapSapient(), world_brain=BasicWorldBrain(), force_char=char, force_world_char=world_char)

        # Give it language
        human.creature.update_language_knowledge(language=self.language, verbal=10, written=0)

        # Transfer the sum of all cultural knowledge to our new creature
        self.setup_entity_knowledge(entity=human, date=born)

        # Placeholder for now, but adding the lingua franca to all those who are part of agricultural socieities
        if self.subsistence == 'agricultural' and g.WORLD.lingua_franca not in human.creature.languages:
            # Update languages to match the lingua franca if necessary
            human.creature.update_language_knowledge(language=g.WORLD.lingua_franca, verbal=10, written=0)

        faction.add_member(human)


        if dynasty is not None:
            dynasty.members.append(human)

        ###### Give them a weapon #######
        if armed:
            material = data.commodity_manager.materials['iron']
            if len(faction.weapons):    wname = random.choice(faction.weapons)
            else:                       wname = random.choice(self.weapons)

            weapon = assemble_object(object_blueprint=phys.object_dict[wname], force_material=material, wx=wx, wy=wy)
            human.initial_give_object_to_hold(weapon)

        ################################
        shirt = assemble_object(object_blueprint=phys.object_dict['shirt'], force_material=None, wx=None, wy=None)
        pants = assemble_object(object_blueprint=phys.object_dict['pants'], force_material=None, wx=None, wy=None)

        human.put_on_clothing(clothing=shirt)
        human.put_on_clothing(clothing=pants)
        # Let them know who owns it
        shirt.set_current_owner(human)
        shirt.set_current_holder(human)
        pants.set_current_owner(human)
        pants.set_current_holder(human)


        # This function will get anytime there needs to be people generated. They don't always need
        # to be saved in the world - thus, we won't worry too much about them if we don't need to
        if save_being:
            g.WORLD.tiles[wx][wy].entities.append(human)
            g.WORLD.tiles[wx][wy].chunk.entities.append(human)

            g.WORLD.all_figures.append(human)
            if important:
                g.WORLD.important_figures.append(human)

        return human

    def create_initial_dynasty(self, faction, wx, wy, wife_is_new_dynasty=0):
        ''' Spits out a dynasty or two, used for to quickly setup new cities'''
        # Create's a dynasty for the leader and his wife
        new_dynasty = Dynasty(lang.spec_cap(random.choice(self.language.vocab_n.values())), race=random.choice(self.races))

        if wife_is_new_dynasty:
            wife_dynasty = Dynasty(lang.spec_cap(random.choice(self.language.vocab_n.values())), race=new_dynasty.race)
        else:
            wife_dynasty = None

        born = g.WORLD.time_cycle.years_ago(roll(28, 40))
        leader = self.create_being(sex=1, born=born, dynasty=new_dynasty, important=1, faction=faction, wx=wx, wy=wy, race=new_dynasty.race, save_being=1)

        born = g.WORLD.time_cycle.years_ago(roll(28, 35))
        wife = self.create_being(sex=0, born=born, dynasty=new_dynasty, important=1, faction=faction, wx=wx, wy=wy, race=new_dynasty.race, save_being=1)
        # Make sure wife takes husband's name
        wife.creature.lastname = new_dynasty.lastname

        marriage_date = g.WORLD.time_cycle.years_ago(roll(6, 10))
        leader.creature.take_spouse(spouse=wife, date=marriage_date)

        all_new_figures = [leader, wife]


        # Leader's siblings
        leader_siblings = []
        for i in xrange(roll(2, 5)):
            sex = roll(0, 1)
            born = g.WORLD.time_cycle.years_ago(roll(28, 40))
            sibling = self.create_being(sex=sex, born=born, dynasty=new_dynasty, important=1, faction=faction, wx=wx, wy=wy, race=new_dynasty.race, save_being=1)
            leader_siblings.append(sibling)
            all_new_figures.append(sibling)

        # Wife's siblings
        if wife_is_new_dynasty:
            wife_siblings = []
            for i in xrange(roll(2, 5)):
                sex = roll(0, 1)
                born = g.WORLD.time_cycle.years_ago(roll(20, 45))
                sibling = self.create_being(sex=sex, born=born, dynasty=new_dynasty, important=1, faction=faction, wx=wx, wy=wy, race=new_dynasty.race, save_being=1)
                wife_siblings.append(sibling)
                all_new_figures.append(sibling)

            wife.creature.siblings = wife_siblings
            for sibling in wife_siblings:
                sibling.creature.siblings.append(wife)

        # have children
        for i in xrange(roll(1, 3)):
            born = g.WORLD.time_cycle.years_ago(roll(1, 10))
            child = wife.creature.have_child(date_born=born)
            all_new_figures.append(child)

        leader.creature.siblings = leader_siblings
        for sibling in leader_siblings:
            sibling.creature.siblings.append(leader)


        # Give a "Noble" profession to any new male members
        for figure in filter(lambda f: f.creature.get_age() >= g.MIN_MARRIAGE_AGE and f not in (leader, wife) and f.creature.sex == 1, all_new_figures):
            profession = Profession(name='Noble', category='noble')
            profession.give_profession_to(figure=figure)

        return leader, all_new_figures


def assemble_object(object_blueprint, force_material, wx, wy, creature=None, local_brain=None, world_brain=None, force_char=None, force_world_char=None):
    ''' Build an object from the blueprint dictionary '''
    ## TODO - Currently only force_material works...

    if creature and creature.faction: color = creature.faction.color
    elif force_material:            color = force_material.color
    else:
        # Not ideal, but when importing xml, we cache all possible materials the object can include - pick a random one for the color
        #print object_blueprint['possible_materials']
        color = data.commodity_manager.materials[random.choice(object_blueprint['possible_materials'])].color

    # Set display character for human-scale map and world map; default to the one defined in the object blueprint if none selected
    char = force_char if force_char else object_blueprint['char']
    world_char = force_world_char if force_world_char else char

    components = phys.assemble_components(clist=object_blueprint['components'], force_material=force_material)

    obj = Object(name = object_blueprint['name'],
                    char = char,
                    world_char = world_char,
                    color = color,
                    components = components,
                    blocks_mov = object_blueprint['blocks_mov'],
                    blocks_vis = object_blueprint['blocks_vis'],
                    description = object_blueprint['description'],

                    creature = creature,
                    local_brain = local_brain,
                    world_brain = world_brain,
                    weapon = object_blueprint['weapon_component'],
                    wx = wx,
                    wy = wy,
                    wearable = object_blueprint['wearable']
                    )
    return obj


def get_info_under_mouse():
    ''' get info to be printed in the sidebar '''
    (x, y) = g.game.camera.cam2map(mouse.cx, mouse.cy)
    info = []
    if g.game.map_scale == 'human' and g.M.is_val_xy((x, y)):
        info.append(('Tick: {0}'.format(g.WORLD.time_cycle.current_tick), g.PANEL_FRONT))
        info.append(('at coords {0}, {1} height is {2}'.format(x, y, g.M.tiles[x][y].height), g.PANEL_FRONT))
        ### This will spit out some info about the unit we've selected (debug stuff)
        if g.game.render_handler.debug_active_unit_dijmap and not g.M.tiles[x][y].blocks_mov:
            debug_unit = g.game.render_handler.debug_active_unit_dijmap
            info.append(('{0}: tick = {1}'.format(debug_unit.fullname(), debug_unit.creature.next_tick), libtcod.copper))
            total_desire = 0
            for desire, amount in debug_unit.creature.dijmap_desires.iteritems():
                if amount < 0: dcolor = libtcod.color_lerp(g.PANEL_FRONT, libtcod.red, amount/100)
                elif amount > 0: dcolor = libtcod.color_lerp(g.PANEL_FRONT, libtcod.green, amount/100)
                else: dcolor = g.PANEL_FRONT
                info.append(('{0}: {1}'.format(desire, amount), dcolor ))

                if g.M.dijmaps[desire].dmap[x][y] is not None:
                    total_desire += (g.M.dijmaps[desire].dmap[x][y] * amount)
            info.append(('Total: {0}'.format(total_desire), libtcod.dark_violet))
            info.append((' ', libtcod.white))
        ###############################################################################

        # Info about the surface of the map
        info.append((g.M.tiles[x][y].surface, libtcod.color_lerp(g.PANEL_FRONT, g.M.tiles[x][y].color, .5) ))
        info.append((' ', libtcod.white))
        # Zoning info
        if g.M.tiles[x][y].zone:
            info.append((g.M.tiles[x][y].zone, g.PANEL_FRONT))
            info.append((' ', g.PANEL_FRONT))
            # Building info
        if g.M.tiles[x][y].building:
            info.append((g.M.tiles[x][y].building.get_name(), g.PANEL_FRONT))
            info.append((' ', g.PANEL_FRONT))

        color = g.PANEL_FRONT
        for obj in g.M.tiles[x][y].objects:
            if libtcod.map_is_in_fov(g.M.fov_map, obj.x, obj.y):
                info.append((obj.fulltitle(), libtcod.color_lerp(g.PANEL_FRONT, obj.color, .3) ))

                if obj.creature and obj.creature.status == 'alive':
                    info.append(('Facing {0}'.format(COMPASS[obj.creature.facing]), libtcod.color_lerp(libtcod.yellow, color, .5) ))

                info.append((' ', color))
                '''
				for component in obj.components:
					if component.grasped_item:
						info.append((component.name + ' (' + component.grasped_item.name + ')', color))
					else:
						info.append((component.name, color))
				'''

    elif g.game.map_scale == 'world' and g.WORLD.is_val_xy((x, y)):
        color = g.PANEL_FRONT
        xc, yc = g.game.camera.map2cam(x, y)
        if 0 <= xc <= g.CAMERA_WIDTH and 0 <= yc <= g.CAMERA_HEIGHT:
            if g.game.state == 'playing':
                info.append(('DBG: Reg{0}, {1}ht, {2}dist'.format(g.WORLD.tiles[x][y].region_number, g.WORLD.tiles[x][y].height, g.WORLD.distance_from_civilization_dmap.dmap[x][y]), libtcod.color_lerp(color, g.WORLD.tiles[x][y].color, .5)))

            info.append((g.WORLD.tiles[x][y].region.capitalize(), libtcod.color_lerp(color, g.WORLD.tiles[x][y].color, .5)))
            ###### Cultures ########
            if g.WORLD.tiles[x][y].culture is not None:
                info.append(('Culture: {0}'.format(g.WORLD.tiles[x][y].culture.name), libtcod.color_lerp(color, g.WORLD.tiles[x][y].culture.color, .3)))
                info.append(('Language: {0}'.format(g.WORLD.tiles[x][y].culture.language.name), libtcod.color_lerp(color, g.WORLD.tiles[x][y].culture.color, .3)))
            else:
                info.append(('No civilized creatures inhabit this region', color))
            ###### Territory #######
            if g.WORLD.tiles[x][y].territory:
                info.append(('Territory of {0}'.format(g.WORLD.tiles[x][y].territory.name), libtcod.color_lerp(color, g.WORLD.tiles[x][y].territory.color, .3)))
            else:
                info.append(('No state\'s borders claim this region', color))
            info.append((' ', color))

            # Resources
            for resource, amount in g.WORLD.tiles[x][y].res.iteritems():
                info.append(('{0} ({1})'.format(resource.capitalize(), amount), color))
            info.append((' ', color))

            region_slot_info = []
            for resource_name, slot_info in g.WORLD.tiles[x][y].agent_slots.iteritems():
                region_slot_info.append('{0} {1}'.format(len(slot_info['agents']), resource_name))
            joined = join_list(region_slot_info)
            info.append((joined, color))
            info.append((' ', color))

            ## FEATURES
            for feature in g.WORLD.tiles[x][y].features + g.WORLD.tiles[x][y].caves:
                info.append((feature.get_name(), color))
            for site in g.WORLD.tiles[x][y].minor_sites:
                info.append(('{} ({})'.format(site.get_name(), site.get_population()), color))
                if site.is_holy_site_to:
                    for pantheon in site.is_holy_site_to:
                        info.append((' - This is considered a holy site to the {0}.'.format(pantheon.name), color ))
            info.append((' ', color))

            # Sites
            site = g.WORLD.tiles[x][y].site
            if site:
                info.append(('The {0} of {1} ({2})'.format(site.type_, site.name.capitalize(), site.get_population()), color))
                if site.type_ == 'city':
                    info.append(('{0} harbored here'.format(ct('caravan', len(site.caravans))), color))
                    num_figures = len([f for f in g.WORLD.tiles[x][y].entities if (f.creature.is_commander() or not f.creature.commander)])
                    info.append(('{0} or {1} here'.format(ct('entity', num_figures), pl('party', num_figures)), color))
            else:
                # Entities
                for entity in g.WORLD.tiles[x][y].entities:
                    # Commanders of parties or armies
                    if entity.creature and entity.creature.is_commander():
                        info.append(('{0} ({1} total)'.format(entity.fulltitle(), ct('man', entity.creature.get_total_number_of_commanded_beings())), libtcod.color_lerp(color, entity.creature.faction.color, .3)))

                    # Individual travellers - exclude those who have a commander
                    elif entity.creature and not entity.creature.commander:
                        info.append(('{0}'.format(entity.fulltitle()), libtcod.color_lerp(color, entity.creature.faction.color, .3)))

                    # Show information about the entity's goals, if it has a brain
                    if entity.world_brain:
                        info.append(('Currently: {0}'.format(entity.world_brain.get_current_behavior()), libtcod.color_lerp(color, entity.creature.faction.color, .3)))
                        info.append(('Eventually: {0}'.format(entity.world_brain.get_final_behavior()), libtcod.color_lerp(color, entity.creature.faction.color, .3)))

                    info.append((' ', color))

                # Only show uncommanded populations
                for population in g.WORLD.tiles[x][y].populations:
                    if not population.commander:
                        info.append(('{0}'.format(population.name)), libtcod.color_lerp(color, population.faction.color, .3))

            info.append((' ', color))

    return info

class RenderHandler:
    def __init__(self):

        self.debug_active_unit_dijmap = None


    def render_tile(self, console, x, y, char, color, background_color):
        ''' Renders a tile, accounting for the fact that each "tile" is now 2 characters wide '''
        libtcod.console_put_char_ex(console, x, y, char, color, background_color)
        libtcod.console_put_char_ex(console, x+1, y, char+1, color, background_color)

    def debug_dijmap_view(self, figure=None):
        if figure is None and self.debug_active_unit_dijmap is not None:
            self.debug_active_unit_dijmap.char = g.PLAYER_TILE
            self.debug_active_unit_dijmap = None

        else:
            self.debug_active_unit_dijmap = figure
            self.debug_active_unit_dijmap.char = g.X_TILE


    def progressbar_screen(self, header, current_action, min_val, max_val, background_text=None):
        root_con.clear()

        libtcod.console_print_ex(root_con.con, int(round(g.SCREEN_WIDTH / 2)), 1, libtcod.BKGND_NONE, libtcod.CENTER, header)

        if background_text:
            y = 10
            for line in background_text:
                h = libtcod.console_print_rect(con=root_con.con, x=20, y=y, w=g.SCREEN_WIDTH-20, h=30, fmt=line)
                y += h + 2


        root_con.render_bar(x=int(round(g.SCREEN_WIDTH / 2)) - 9, y=20, total_width=18, name=current_action, value=min_val,
                   maximum=max_val, bar_color=libtcod.color_lerp(libtcod.dark_yellow, g.PANEL_FRONT, .5),
                   back_color=g.PANEL_BACK, text_color=g.PANEL_FRONT, show_values=False, title_inset=False)

        libtcod.console_flush()

    def blink(self, x, y, color, repetitions, speed):
        # Have a tile blink at specified speed for specified # of repetitions
        (wmap_x, wmap_y) = g.game.camera.cam2map(x, y)

        g.game.render_handler.render_all(do_flush=1)

        for repetition in xrange(repetitions):
            # Render red
            g.game.render_handler.render_tile(g.game.interface.map_console.con, x, y, g.X_TILE, color, color)

            libtcod.console_blit(g.game.interface.map_console.con, 0, 0, g.CAMERA_WIDTH, g.CAMERA_HEIGHT, 0, 0, 0)
            libtcod.console_flush()
            time.sleep(speed)

            # Render background color
            g.game.render_handler.render_tile(g.game.interface.map_console.con, x, y, g.WORLD.tiles[wmap_x][wmap_y].char, g.WORLD.tiles[wmap_x][wmap_y].char_color, g.WORLD.tiles[wmap_x][wmap_y].color)

            libtcod.console_blit(g.game.interface.map_console.con, 0, 0, g.game.camera.width, g.game.camera.height, 0, 0, 0)
            libtcod.console_flush()
            time.sleep(speed)

    def render_all(self, do_flush=1):

        if g.game.map_scale == 'human' and g.M.fov_recompute:
            g.M.display(self.debug_active_unit_dijmap)

        elif g.game.map_scale == 'world':
            g.WORLD.display()

        # Handle the basic rendering steps on the GUI panels
        for panel in g.game.interface.gui_panels:
            panel.render_panel(g.game.map_scale, mouse)

        # Debug - print FPS
        libtcod.console_print(panel2.con, x=2, y=1, fmt='%i FPS' %int(libtcod.sys_get_fps()) )

        if g.game.state == 'playing':
            # Current date and time info
            libtcod.console_print(panel2.con, 2, 2, g.WORLD.time_cycle.date_to_text(g.WORLD.time_cycle.get_current_date()))
            if g.game.map_scale == 'world':
                libtcod.console_print(panel2.con, 2, 3, '{0} year of {1}'.format(int2ord(1 + g.WORLD.time_cycle.current_year - g.player.creature.faction.leader_change_year), g.player.creature.faction.leader.fullname() ))
                libtcod.console_print(panel2.con, 2, 4, '({0}); {1} pop, {2} imp'.format(g.WORLD.time_cycle.current_year, len(g.WORLD.all_figures), len(g.WORLD.important_figures)))
                libtcod.console_print(panel2.con, 2, 5, '{0} events'.format(len(hist.historical_events)))

            ##### PANEL 4 - ECONOMY STUFF
            if g.player.creature.economy_agent is not None:
                libtcod.console_set_default_foreground(panel4.con, g.PANEL_FRONT)

                if panel4.recalculate_wmap_dyn_buttons: # TODO - this should go inside the gui panel logic, along with passing the new buttons to be recalculated!
                    panel4.wmap_dynamic_buttons = []

                agent = g.player.creature.economy_agent
                y = 2
                libtcod.console_print(panel4.con, 2, y, agent.name + ' (' + agent.economy.owner.name + ')')
                y +=  1
                libtcod.console_print(panel4.con, 2, y, str(agent.gold) + ' gold')


                # Display price beliefs and inventory

                # Display inventory
                inv = Counter(agent.inventory)
                for item, amount in inv.iteritems():
                    y += 1
                    libtcod.console_print(panel4.con, 2, y, '{0}: {1}'.format(item, amount))
                    libtcod.console_print(panel4.con, 30, y, '{0} to {1}'.format(agent.perceived_values[item].center - agent.perceived_values[item].uncertainty, agent.perceived_values[item].center + agent.perceived_values[item].uncertainty))

                y += 2
                libtcod.console_print(panel4.con, 2, y, '-* Last turn *-')
                h = 1
                for action in agent.last_turn:
                    y += h
                    h = libtcod.console_print_rect(panel4.con, 2, y, g.PANEL4_WIDTH -4, 2, ' - ' + action)

                    if y > 50: # Hardcoded cutoff Y value
                        y += 1
                        libtcod.console_print_rect(panel4.con, 2, y, g.PANEL4_WIDTH -4, 2, ' <more> ')
                        break

                y += 2
                libtcod.console_print(panel4.con, 2, y, '-* Future buys *-')
                for item, [bid_price, bid_quantity] in agent.future_bids.iteritems():
                    y += 1
                    libtcod.console_print(panel4.con, 2, y, str(bid_quantity) + ' ' + item + ' @ ' + str(bid_price) )


                    if panel4.recalculate_wmap_dyn_buttons:
                        panel4.wmap_dynamic_buttons.append(gui.Button(gui_panel=panel4, func=g.player.creature.economy_agent.change_bid_price, args=(item, -1),
                                                                      text='<', topleft=(g.PANEL4_WIDTH-3, y), width=1, height=1, color=libtcod.light_blue, do_draw_box=False) )
                        panel4.wmap_dynamic_buttons.append(gui.Button(gui_panel=panel4, func=g.player.creature.economy_agent.change_bid_price, args=(item, 1),
                                                                      text='>', topleft=(g.PANEL4_WIDTH-2, y), width=1, height=1, color=libtcod.light_blue*1.3, do_draw_box=False) )

                        panel4.wmap_dynamic_buttons.append(gui.Button(gui_panel=panel4, func=g.player.creature.economy_agent.change_bid_quant, args=(item, -1),
                                                                      text='<', topleft=(g.PANEL4_WIDTH-5, y), width=1, height=1, color=libtcod.light_violet, do_draw_box=False) )
                        panel4.wmap_dynamic_buttons.append(gui.Button(gui_panel=panel4, func=g.player.creature.economy_agent.change_bid_quant, args=(item, 1),
                                                                      text='>', topleft=(g.PANEL4_WIDTH-4, y), width=1, height=1, color=libtcod.light_violet*1.3, do_draw_box=False) )

                y += 1
                libtcod.console_print(panel4.con, 2, y, '-* Future sells *-')
                for item, [sell_price, sell_quantity] in agent.future_sells.iteritems():
                    y += 1
                    libtcod.console_print(panel4.con, 2, y, str(sell_quantity) + ' ' + item + ' @ ' + str(sell_price) )


                    if panel4.recalculate_wmap_dyn_buttons:
                        panel4.wmap_dynamic_buttons.append(gui.Button(gui_panel=panel4, func=g.player.creature.economy_agent.change_sell_price, args=(item, -1),
                                                                      text='<', topleft=(g.PANEL4_WIDTH-3, y), width=1, height=1, color=libtcod.light_blue, do_draw_box=False) )
                        panel4.wmap_dynamic_buttons.append(gui.Button(gui_panel=panel4, func=g.player.creature.economy_agent.change_sell_price, args=(item, 1),
                                                                      text='>', topleft=(g.PANEL4_WIDTH-2, y), width=1, height=1, color=libtcod.light_blue*1.3, do_draw_box=False) )

                        panel4.wmap_dynamic_buttons.append(gui.Button(gui_panel=panel4, func=g.player.creature.economy_agent.change_sell_quant, args=(item, -1),
                                                                      text='<', topleft=(g.PANEL4_WIDTH-5, y), width=1, height=1, color=libtcod.light_violet, do_draw_box=False) )
                        panel4.wmap_dynamic_buttons.append(gui.Button(gui_panel=panel4, func=g.player.creature.economy_agent.change_sell_quant, args=(item, 1),
                                                                      text='>', topleft=(g.PANEL4_WIDTH-4, y), width=1, height=1, color=libtcod.light_violet*1.3, do_draw_box=False) )


                if panel4.recalculate_wmap_dyn_buttons:
                    panel4.recalculate_wmap_dyn_buttons = 0

            ## Panel 3 - g.player info ##
            libtcod.console_print_ex(panel3.con, int(round(g.PANEL3_WIDTH / 2)), 1, libtcod.BKGND_NONE, libtcod.CENTER, '-* {0} *-'.format(g.player.fullname()))

            libtcod.console_print(panel3.con, 2, 3, g.player.creature.status)
            # A list of things to display
            y = 4
            for grasper in g.player.creature.get_graspers():
                if grasper.grasped_item:
                    y += 1
                    libtcod.console_print(panel3.con, 2, y, '{0} ({1})'.format(grasper.grasped_item.name, grasper.name))

            y += 2
            wearing_info = join_list([indef(c.name) for c in g.player.wearing])
            libtcod.console_print_rect(panel3.con, 2, y, panel3.width-2, panel3.height-y, 'Wearing {0}'.format(wearing_info))


            ## bar showing current pain amount ##
            #panel3.render_bar(x=2, y=panel3.height - 4, total_width=panel3.width - 4, name='Pain',
            #           value=g.player.creature.get_pain(), maximum=g.player.creature.get_max_pain(),
            #           bar_color=g.PAIN_FRONT, back_color=g.PAIN_BACK, text_color=libtcod.black, show_values=True,
            #           title_inset=True)
            ### Done rendering player info ###

            if g.game.map_scale == 'human':
                battle_hover_information()

        y = 6
        for (line, color) in get_info_under_mouse():
            ## Quick fix to catch more text than panel height
            if y > g.PANEL2_HEIGHT - 4:
                libtcod.console_print(panel2.con, g.PANEL2_TEXTX, y, '<< More >>')
                break
                ## Otherwise, print the info in whatever color it was specified as
            if not line == ' ':
                splitline = textwrap.wrap(line, g.PANEL2_WIDTH - g.PANEL2_TEXTX - 2)
            else:
                splitline = ' '
            for nline in splitline:
                libtcod.console_set_default_foreground(panel2.con, color)
                libtcod.console_print(panel2.con, g.PANEL2_TEXTX, y, nline)
                y += 1

        #print the game messages
        y = 1
        for (line, color) in g.game.get_game_msgs():
            libtcod.console_set_default_foreground(panel1.con, color)
            libtcod.console_print(panel1.con, g.MSG_X, y, line)
            y += 1

        #blit the contents of "panel" to the root console
        for panel in g.game.interface.gui_panels:
            if panel.render:
                panel.blit()
        # Special priority for the hover information panel
        if g.game.interface.hover_info:
            g.game.interface.hover_info.hover()

        if do_flush:
            libtcod.console_flush()

        for panel in g.game.interface.panel_deletions[:]:
            g.game.interface.delete_panel(panel)


def battle_hover_information():
    ''' Displays a box summarizing some combat stats on mouse hover '''
    (x, y) = g.game.camera.cam2map(mouse.cx, mouse.cy)  #from screen to map coordinates

    target = None
    if g.game.camera.mouse_is_on_map() and g.M.is_val_xy((x, y)) and g.M.tiles[x][y].explored:
        for obj in g.M.tiles[x][y].objects:
            if obj.creature and obj.creature.is_available_to_act():
                target = obj
                break

        other_objects = [obj for obj in g.M.tiles[x][y].objects if (not obj.creature) or (obj.creature and obj.creature.status == 'dead') ]

        if g.M.tiles[x][y].interactable:
            itext = g.M.tiles[x][y].interactable['hover_text']
            gui.HoverInfo(header=['Interact'], text=itext, cx=mouse.cx, cy=mouse.cy, hoffset=1, textc=g.PANEL_FRONT, bcolor=g.PANEL_FRONT, transp=.8, interface=g.game.interface)

        ####### FOR OTHER OBJECTS ######
        if len(other_objects) > 0:
            oheader = ['Objects:']

            otext = []
            for obj in other_objects:
                otext.append(obj.fullname())
                otext.append(obj.description)

                otext.append('Damage:')
                for wound in obj.get_wound_descriptions():
                    otext.append(wound)
                otext.append('')


            gui.HoverInfo(header=oheader, text=otext, cx=mouse.cx+1, cy=mouse.cy+1, hoffset=1, textc=g.PANEL_FRONT, bcolor=g.PANEL_FRONT, transp=.8, interface=g.game.interface, xy_corner=1)

        ######## FOR SAPIENTS ###########
        if target and target.creature:
            header = [target.fulltitle()]

            inventory = target.get_inventory()

            header.append('Wearing {0}'.format(join_list([indef(item.name) for item in inventory['clothing'] ])))
            header.append('Holding {0}'.format(join_list([indef(item.name) for item in inventory['grasped'] ])))
            header.append('Storing {0}'.format(join_list([indef(item.name) for item in inventory['stored'] ])))

            text = [skill + ': ' + str(value) for skill, value in target.creature.skills.iteritems()]
            text.insert(0, target.creature.stance + ' stance')

            description = textwrap.wrap(target.description, 40)
            # Beginning with the last line, add each line of the description to the hover info
            text.insert(0, '')
            for line in reversed(description):
                text.insert(0, line)

            text.append(' ')
            wounds = target.get_wound_descriptions()
            text.append('{0}{1}'.format(ct('wound', len(wounds)), ':' if len(wounds) else ''))
            for wound in wounds:
                text.append(wound)
            text.append(' ')

            if target.local_brain:
                text.append(' :- - - - - - - : ')
                text.append('State: %s'%target.local_brain.ai_state )
                text.append('Target_fig: %s'%target.local_brain.target_figure.fullname() if target.local_brain.target_figure else 'Target_fig: None' )
                text.append('Target_loc: %s, %s'%(target.local_brain.target_location[0], target.local_brain.target_location[1]) if target.local_brain.target_location else 'Target_loc: None' )
                text.append('Path reset: %s'%target.local_brain.astar_refresh_cur )
                text.append('Closest_enemy: {0}'.format(target.local_brain.perception_info['closest_enemy'].fullname() if target.local_brain.perception_info['closest_enemy'] else 'None'))
                text.append('Closest_dist: %s'%target.local_brain.perception_info['closest_enemy_distance'])
                #text.append('State: ' + target.local_brain.ai_state )

            gui.HoverInfo(header=header, text=text, cx=mouse.cx, cy=mouse.cy, textc=g.PANEL_FRONT, bcolor=g.PANEL_FRONT, transp=.8, interface=g.game.interface)

        ### If it's a non-creature creature....
        elif target:
            header = [target.fullname()]
            text = [target.description]

            if target.local_brain:
                text.append('')
                text.append('AI State: %s' %target.local_brain.ai_state )

            gui.HoverInfo(header=header, text=text, cx=mouse.cx, cy=mouse.cy, textc=g.PANEL_FRONT, bcolor=g.PANEL_FRONT, transp=.8, interface=g.game.interface)
        ######################################

        ## Only handle recompute if there's something uner the cursor
        ## TODO - still halves FPS while hovering over objects - this should only recompute FOV if the mouse moves
        if target or len(other_objects):
            g.game.handle_fov_recompute()


def infobox(header, options, xb=0, yb=0, xoffset=2, yoffset=2, textc=libtcod.grey, bcolor=libtcod.black, transp=.5):

    ## First find width of the box
    total_width = xoffset * 2
    for column in options:
        total_width += len(max(column, key=len)) + 1 # Add 1 as spacer between each column
        ## Then find height of the box
    if header == '':
        header_height = 0
    else:
        header_height = 3
    height = len(max(options, key=len)) + header_height + (yoffset * 2)

    # Give box center coords
    if xb == 0 and yb == 0:
        xb = int(round(g.SCREEN_WIDTH / 2)) - int(round(total_width / 2))
        yb = int(round(g.SCREEN_HEIGHT / 2)) - int(round(height / 2))

    #create an off-screen console that represents the menu's window
    wpanel = gui.GuiPanel(width=total_width, height=height, xoff=0, yoff=0, interface=g.game.interface,
                          is_root=0, append_to_panels=0)

    # Blit window once with desired transparency.
    libtcod.console_blit(wpanel.con, 0, 0, total_width, height, 0, xb, yb, 1.0, transp)

    event = libtcod.sys_check_for_event(libtcod.EVENT_KEY_PRESS | libtcod.EVENT_MOUSE, key, mouse)
    while not mouse.lbutton:
        #print the header, with auto-wrap
        libtcod.console_set_default_foreground(wpanel.con, textc)
        libtcod.console_print(wpanel.con, xoffset, yoffset, header)

        cur_width = xoffset
        #print all the options
        for column in options:
            y = header_height + yoffset
            width = len(max(column, key=len))
            for entry in column:
                libtcod.console_set_default_foreground(wpanel.con, textc)
                libtcod.console_print(wpanel.con, cur_width, y, entry)
                y += 1

            cur_width += width + 1

        # Draw box around menu if parameter is selected
        if bcolor is not None:
            wpanel.draw_box(0, total_width - 1, 0, height - 1, bcolor)

        # Blit to root console + flush to present changes
        libtcod.console_blit(wpanel.con, 0, 0, total_width, height, 0, xb, yb, 1.0, 0)
        libtcod.console_flush()

        event = libtcod.sys_check_for_event(libtcod.EVENT_KEY_PRESS | libtcod.EVENT_MOUSE, key, mouse)
        (mx, my) = (mouse.cx, mouse.cy)

    libtcod.console_delete(wpanel.con)

    #g.game.handle_fov_recompute()
    #g.game.render_handler.render_all()


def show_object_info(obj):
    ## Display information about a creature and it's status
    objlist = []
    complist = []

    objlist.append('Mass: ' + str(round(obj.get_mass(), 2)) + 'kg')
    objlist.append('Density: ' + str(round(obj.get_density(), 2)) + 'kg/m^3')

    if obj.creature:
        objlist.append('Movespeed: ' + str(obj.creature.attributes['movespeed']))
        objlist.append('Blood: ' + str(obj.creature.blood))
        objlist.append('Bleeding: ' + str(obj.creature.bleeding))

    for component in obj.components:
        name = component.name
        mass = str(round(component.get_mass(), 2))
        density = str(round(component.get_density(), 2))

        comptitle = ''.join([name, ': ', mass, 'kg, ', density, 'kg/m^3'])

        if component.grasped_item is not None:
            comptitle += '. Holding {0}'.format(indef(component.grasped_item.name))

        complist.append(comptitle)
        ### Display attachments (packs, bags, etc)
        attached_items = []
        for attached_item_component in component.attachments:
            if attached_item_component.owner != obj and attached_item_component.owner not in attached_items:
                attached_items.append(attached_item_component.owner)

        for item in attached_items:
            complist.append(item.name)


        for layer in component.layers:
            lname = layer.material.name
            cov = str(layer.coverage)
            health = str(round(layer.health, 2) * 100)

            linfo = ' - ' + lname + ' (' + health + ' health, ' + cov + ' coverage)'
            complist.append(linfo)

        complist.append(' ')

    infobox(header=obj.name, options=[objlist, complist], xb=1, yb=1,
            xoffset=2, yoffset=2, textc=libtcod.white,
            bcolor=obj.color, transp=.8)

    g.game.handle_fov_recompute()
    #g.game.render_handler.render_all()



class Game:
    def __init__(self, interface, render_handler):

        self.interface = interface
        self.interface.set_game(self)

        self.render_handler = render_handler

        self.state = 'worldgen'
        self.map_scale = 'world'
        self.world_map_display_type = 'normal'

        self.camera = Camera(width_in_characters=g.CAMERA_WIDTH, height=g.CAMERA_HEIGHT)

        self.msgs = []

        self.quit_game = 0

        self.msg_index = 0


    def get_game_msgs(self):
        ''' Get the messages to display '''
        if len(self.msgs) < g.MSG_HEIGHT:
            return self.msgs
        else:
            return self.msgs[self.msg_index:(self.msg_index + g.MSG_HEIGHT)]


    def set_msg_index(self, amount=None):
        ''' Sets the index from which messages will be read.
        Makes sure that the message index will stat within appropriate bounds '''
        if amount is None:
            self.msg_index = max(0, len(self.msgs) - g.MSG_HEIGHT)

        elif self.msg_index + amount < 0:
            self.msg_index = 0

        elif self.msg_index + amount > len(self.msgs) - g.MSG_HEIGHT:
            self.msg_index = len(self.msgs) - g.MSG_HEIGHT

        else:
            self.msg_index = self.msg_index + amount

    def add_message(self, new_msg, color=libtcod.white):
        #split the message if necessary, among multiple lines
        new_msg_lines = textwrap.wrap(new_msg, g.MSG_WIDTH)

        for line in new_msg_lines:
            #if the buffer is full, remove the first line to make room for the new one
            if len(self.msgs) == g.MSG_HEIGHT * 10:
                del self.msgs[0]
                #add the new line as a tuple, with the text and the color
            self.msgs.append((line, color))

        self.set_msg_index()


    def switch_to_quit_game(self):
        self.quit_game = 1

    def switch_map_scale(self, map_scale):
        ''' Toggles map state between larger "world" view and human-scaled map '''
        bwidth = 20
        self.map_scale = map_scale

        if self.map_scale == 'human':

            panel2.bmap_buttons = [
                                   gui.Button(gui_panel=panel2, func=player_order_move, args=[], text='Move!', topleft=(4, g.PANEL2_HEIGHT-22), width=10, height=4),
                                   gui.Button(gui_panel=panel2, func=player_order_follow, args=[], text='Follow Me!', topleft=(14, g.PANEL2_HEIGHT-22), width=10, height=4),

                                   gui.Button(gui_panel=panel2, func=debug_menu, args=[], text='Debug Panel', topleft=(4, g.PANEL2_HEIGHT-18), width=bwidth, height=4),
                                   gui.Button(gui_panel=panel2, func=self.return_to_worldmap, args=[], text='Return to World view', topleft=(4, g.PANEL2_HEIGHT-14), width=20, height=4),
                                   gui.Button(gui_panel=panel2, func=pick_up_menu, args=[], text='Pick up item', topleft=(4, g.PANEL2_HEIGHT-10), width=20, height=4),
                                   gui.Button(gui_panel=panel2, func=manage_inventory, args=[], text='Inventory', topleft=(4, g.PANEL2_HEIGHT-6), width=20, height=4)
                                   ]

        elif self.map_scale == 'world':

            panel2.wmap_buttons = [
                                   gui.Button(gui_panel=panel2, func=debug_menu, args=[], text='Debug Panel', topleft=(4, g.PANEL2_HEIGHT-18), width=bwidth, height=4),
                                   gui.Button(gui_panel=panel2, func=g.WORLD.goto_scale_map, args=[], text='Go to scale map', topleft=(4, g.PANEL2_HEIGHT-14), width=bwidth, height=4),
                                   gui.Button(gui_panel=panel2, func=gui.show_civs, args=[g.WORLD], text='Civ info', topleft=(4, g.PANEL2_HEIGHT-10), width=bwidth, height=4),
                                   gui.Button(gui_panel=panel2, func=gui.show_cultures, args=[g.WORLD, None], text='Cultures', topleft=(4, g.PANEL2_HEIGHT-6), width=bwidth, height=4)
                                   ]

    def handle_fov_recompute(self):
        ''' FOV / map is only re-rendered when fov_recompue is set to true '''
        if self.map_scale == 'world':
            g.WORLD.fov_recompute = 1
        elif self.map_scale == 'human':
            g.M.fov_recompute = 1


    def save_game(self):
        #open a new empty shelve (possibly overwriting an old one) to write the game data
        #save_file = shelve.open('savegame', 'n')
        save_file['g.WORLD'] = g.WORLD
        #save_file['time_cyle'] = g.time_cycle
        save_file.close()

    def load_game(self):
        #open the previously saved shelve and load the game data
        #global M, g.WORLD, g.player, g.time_cycle
        #file = shelve.open('savegame', 'r')
        g.WORLD = file['g.WORLD']
        #g.time_cycle = file['time_cyle']
        file.close()


    def create_new_world_and_begin_game(self):
        # Gen world
        g.WORLD = None # Clear in case previous world was generated
        g.WORLD = World(g.WORLD_WIDTH, g.WORLD_HEIGHT)
        g.WORLD.generate()

        self.camera.center(int(round(g.WORLD.width / 2)), int(round(g.WORLD.height / 2)))

        self.game_main_loop()


    def new_game(self):
        self.switch_map_scale(map_scale='world')

        g.playerciv = g.WORLD.cities[0]
        born = g.WORLD.time_cycle.years_ago(roll(20, 45))
        g.player = g.playerciv.get_culture().create_being(sex=1, born=born, char=g.PLAYER_TILE, dynasty=None, important=0, faction=g.playerciv.get_faction(), armed=1, wx=g.playerciv.x, wy=g.playerciv.y)
        # Make player literate
        for language in g.player.creature.languages:
            g.player.creature.update_language_knowledge(language=language, verbal=0, written=g.player.creature.languages[language]['verbal'])

        g.WORLD.tiles[g.player.wx][g.player.wy].entities.append(g.player)
        g.WORLD.tiles[g.player.wx][g.player.wy].chunk.entities.append(g.player)

        g.player.color = libtcod.cyan
        g.player.local_brain = None
        g.player.world_brain = None

        self.camera.center(g.player.wx, g.player.wy)
        self.state = 'playing'


    def game_main_loop(self):
        ''' Main game loop - handles input and renders map '''
        while not libtcod.console_is_window_closed():
            #render the screen
            self.render_handler.render_all(do_flush=True)
            #libtcod.console_flush()

            #handle keys and exit game if needed
            action = self.handle_keys()

            if self.quit_game or action == 'exit':
                #save_game()
                break


    def setup_quick_battle(self):
        ''' A quick and dirty battle testing arena, more or less. Will need a massive overhaul
            at some point, if it even stays in '''

        t1 = time.time()
        ##################### Create a dummy world just for the quick battle
        g.WORLD = World(width=3, height=3)
        g.WORLD.setup_world()
        g.WORLD.generate_sentient_races()
        cult = Culture(color=libtcod.grey, language=lang.Language(), world=g.WORLD, races=g.WORLD.sentient_races)
        for x in xrange(g.WORLD.width):
            for y in xrange(g.WORLD.height):
                g.WORLD.tiles[x][y].region = 'grass savanna'
                g.WORLD.tiles[x][y].color = libtcod.Color(95, 110, 68)
                g.WORLD.tiles[x][y].culture = cult
                g.WORLD.tiles[x][y].height = 120

        ########### Factions ################
        faction1 = Faction(leader_prefix='King', name='Player faction', color=random.choice(g.CIV_COLORS), succession='dynasty')
        faction2 = Faction(leader_prefix='King', name='Enemy faction', color=random.choice(g.CIV_COLORS), succession='dynasty', defaultly_hostile=1)
        # Set them as enemies (function will do so reciprocally)
        #faction1.set_enemy_faction(faction=faction2)

        ### Make the player ###
        born = g.WORLD.time_cycle.years_ago(roll(20, 40))
        g.player = cult.create_being(sex=1, born=born, char=g.PLAYER_TILE, dynasty=None, important=1, faction=faction1, armed=0, wx=1, wy=1, save_being=1)
        #g.player.creature.skills['fighting'] += 100
        g.player.char = g.PLAYER_TILE
        g.player.local_brain = None

        sentients = {cult:{random.choice(cult.races):{'Adventurers':10}}}
        g.player_party = g.WORLD.create_population(char=g.PLAYER_TILE, name="Player party", faction=faction1, creatures={}, sentients=sentients, econ_inventory={}, wx=1, wy=1, commander=g.player)


        born = g.WORLD.time_cycle.years_ago(roll(20, 40))
        leader = cult.create_being(sex=1, born=born, char=g.PLAYER_TILE, dynasty=None, important=1, faction=faction2, armed=1, wx=1, wy=1, save_being=1)
        sentients = {cult:{random.choice(cult.races):{'Bandits':10}}}
        enemy_party = g.WORLD.create_population(char=g.PLAYER_TILE, name="Enemy party", faction=faction2, creatures={}, sentients=sentients, econ_inventory={}, wx=1, wy=1, commander=leader)


        hideout_site = g.WORLD.tiles[1][1].create_and_add_minor_site(world=g.WORLD, type_='hideout', char=g.HIDEOUT_TILE, name='Hideout', color=libtcod.black)
        hideout_building = hideout_site.create_building(zone='residential', type_='hideout', template='temple1', professions=[], inhabitants=[], tax_status=None)

        faction1.set_leader(leader=g.player)
        faction2.set_leader(leader=leader)
        # Weapons for variety
        faction1.create_faction_objects()
        faction2.create_faction_objects()

        # Give weapon to g.player
        wname = random.choice(faction1.weapons)
        weapon = assemble_object(object_blueprint=phys.object_dict[wname], force_material=data.commodity_manager.materials['iron'], wx=None, wy=None)
        g.player.initial_give_object_to_hold(weapon)

        g.player.make_trade(other=leader, my_trade_items=[g.player.creature.get_current_weapon()], other_trade_items=[leader.creature.get_current_weapon()], price=0)
        #g.WORLD.tiles[1][0].features.append(Feature(type_='river', x=1, y=0))
        #g.WORLD.tiles[1][1].features.append(Feature(type_='river', x=1, y=1))
        #g.WORLD.tiles[1][2].features.append(Feature(type_='river', x=1, y=2))
        #####################################################################

        self.switch_map_scale(map_scale='human')
        self.state = 'playing'


        ## Make map
        g.M = Wmap(world=g.WORLD, wx=1, wy=1, width=g.MAP_WIDTH, height=g.MAP_HEIGHT)
        hm = g.M.create_heightmap_from_surrounding_tiles()
        base_color = g.WORLD.tiles[1][1].get_base_color()
        g.M.create_map_tiles(hm=hm, base_color=base_color, explored=1)
        g.M.run_cellular_automata(cfg=g.MCFG[g.WORLD.tiles[x][y].region])
        g.M.add_minor_sites_to_map()
        g.M.color_blocked_tiles(cfg=g.MCFG[g.WORLD.tiles[x][y].region])
        g.M.add_vegetation(cfg=g.MCFG[g.WORLD.tiles[x][y].region])
        g.M.set_initial_dmaps()
        g.M.add_sapients_to_map(entities=g.WORLD.tiles[1][1].entities, populations=g.WORLD.tiles[1][1].populations)


        pack = assemble_object(object_blueprint=phys.object_dict['pack'], force_material=None, wx=None, wy=None)
        g.player.put_on_clothing(clothing=pack)

        self.camera.center(g.player.x, g.player.y)

        self.add_message('loaded in %.2f seconds' %(time.time() - t1))

        # Finally, start the main game loop
        self.game_main_loop()


    def return_to_worldmap(self):
        '''
        file = shelve.open('g.WORLD' + str(g.player_party.x) + str(g.player_party.y), 'n')
        file['map'] = map
        file['g.WORLD' + str(g.player_party.x) + str(g.player_party.y) + '.objects'] = objects
        file.close()
        '''
        g.M.clear_objects()

        self.switch_map_scale(map_scale='world')
        self.camera.center(g.player.wx, g.player.wy)


    def handle_keys(self):
        global mouse, key

        event = libtcod.sys_check_for_event(libtcod.EVENT_KEY_PRESS | libtcod.EVENT_MOUSE, key, mouse)
        #test for other keys
        key_char = chr(key.c)

        (x, y) = self.camera.cam2map(mouse.cx, mouse.cy)

        if key.vk == libtcod.KEY_ENTER and key.lalt:
            #Alt+Enter: toggle fullscreen
            libtcod.console_set_fullscreen(not libtcod.console_is_fullscreen())

        if key.vk == libtcod.KEY_F12:
            #libtcod.sys_save_screenshot('E:\Dropbox\test.png')
            libtcod.sys_save_screenshot()

        elif key.vk == libtcod.KEY_ESCAPE:
            return 'exit'  #exit game

        if mouse.lbutton and self.camera.mouse_is_on_map():
            self.camera.click_and_drag(mouse)

        if mouse.wheel_up:
            self.set_msg_index(amount=-1)
        elif mouse.wheel_down:
            self.set_msg_index(amount=1)

        if self.state == 'playing':

            if self.map_scale == 'world':
                if key_char == 't':
                    if self.world_map_display_type == 'normal':
                        self.world_map_display_type = 'culture'
                    elif self.world_map_display_type == 'culture':
                        self.world_map_display_type = 'territory'
                    elif self.world_map_display_type == 'territory':
                        self.world_map_display_type = 'resource'
                    elif self.world_map_display_type == 'resource':
                        self.world_map_display_type = 'normal'

            if self.map_scale == 'human':
                if mouse.lbutton_pressed and self.camera.mouse_is_on_map():
                    # Clicking on a fellow sapient lets you talk to it
                    if len(g.M.tiles[x][y].objects) or g.M.tiles[x][y].interactable:
                        choose_object_to_interact_with(objs=g.M.tiles[x][y].objects, x=x, y=y)
                        #self.handle_fov_recompute()

                if key_char == 'n':
                    self.render_handler.debug_dijmap_view(figure=None)
                    self.handle_fov_recompute()

            #movement keys
            if key.vk == libtcod.KEY_UP or key_char == 'w' or key.vk == libtcod.KEY_KP8:
                self.player_move_or_attack(0, -1)

            elif key.vk == libtcod.KEY_DOWN or key_char == 'x' or key.vk == libtcod.KEY_KP2:
                self.player_move_or_attack(0, 1)

            elif key.vk == libtcod.KEY_LEFT or key_char == 'a' or key.vk == libtcod.KEY_KP4:
                self.player_move_or_attack(-1, 0)

            elif key.vk == libtcod.KEY_RIGHT or key_char == 'd' or key.vk == libtcod.KEY_KP6:
                self.player_move_or_attack(1, 0)

            elif key.vk == libtcod.KEY_SPACE or key_char == 's' or key.vk == libtcod.KEY_KP5:
                self.player_move_or_attack(0, 0)

            elif key_char == 'q' or key.vk == libtcod.KEY_KP7:
                self.player_move_or_attack(-1, -1)

            elif key_char == 'e' or key.vk == libtcod.KEY_KP9:
                self.player_move_or_attack(1, -1)

            elif key_char == 'c' or key.vk == libtcod.KEY_KP3:
                self.player_move_or_attack(1, 1)

            elif key_char == 'z' or key.vk == libtcod.KEY_KP1:
                self.player_move_or_attack(-1, 1)


        elif self.state == 'worldgen':
            if key.vk == libtcod.KEY_UP:
                self.camera.move(0, -10)

            elif key.vk == libtcod.KEY_DOWN:
                self.camera.move(0, 10)

            elif key.vk == libtcod.KEY_LEFT:
                self.camera.move(-10, 0)

            elif key.vk == libtcod.KEY_RIGHT:
                self.camera.move(10, 0)

    def get_key(self, key):
        ''' 'return either libtcod code or character that was pressed '''
        if key.vk == libtcod.KEY_CHAR:
            return chr(key.c)
        else:
            return key.vk


    def player_advance_time(self, ticks):
        g.WORLD.time_cycle.rapid_tick(ticks)

        # TODO - make much more efficient
        self.handle_fov_recompute()

    def player_move_or_attack(self, dx, dy):
        if self.map_scale == 'human':
            #the coordinates the g.player is moving to/attacking
            x = g.player.x + dx
            y = g.player.y + dy

            if g.M.is_val_xy((x, y)):
                #try to find an attackable object there
                target = None
                for obj in g.M.tiles[x][y].objects:
                    if obj.creature and obj.creature.is_available_to_act() and (obj.creature and g.player.creature.faction.is_hostile_to(obj.creature.faction) ):
                        target = obj
                        break
                #attack if target found, move otherwise
                if target is not None:
                    ## TODO - drop random attacks when you try to move to the tile?
                    ## Or should just use whatever AI ends up happening
                    weapon = g.player.creature.get_current_weapon()
                    if weapon:
                        opening_move = random.choice([m for m in combat.melee_armed_moves if m not in g.player.creature.last_turn_moves])
                        move2 = random.choice([m for m in combat.melee_armed_moves if m != opening_move and m not in g.player.creature.last_turn_moves])
                        g.player.creature.set_combat_attack(target=target, opening_move=opening_move, move2=move2)

                else:
                    g.player.move_and_face(dx, dy)
                # Advance time!
                self.player_advance_time(g.player.creature.attributes['movespeed'])

                self.camera.center(g.player.x, g.player.y)

        elif self.map_scale == 'world':
            # Change back to allow blocked movement and non-glitchy battlemap
            g.player.w_move(dx, dy)
            g.WORLD.time_cycle.day_tick()
            self.camera.center(g.player.wx, g.player.wy)


def main_menu():

    b_width = 20
    # Set button origin points
    bx = int(round(g.SCREEN_WIDTH / 2)) - int(round(b_width/2))
    sty = int(round(g.SCREEN_HEIGHT / 2.5))
    ## List of y vals for the buttons
    bys = []
    for i in range(4):
        bys.append(sty + (i * 7))
        ## The buttons themselves
    buttons = [gui.Button(gui_panel=root_con, func=g.game.create_new_world_and_begin_game, args=[],
                          text='Generate World', topleft=(bx, bys[0]), width=b_width, height=6, color=g.PANEL_FRONT, do_draw_box=True),
               gui.Button(gui_panel=root_con, func=g.game.setup_quick_battle, args=[],
                          text='Quick Battle', topleft=(bx, bys[1]), width=b_width, height=6, color=g.PANEL_FRONT, do_draw_box=True),
               #gui.Button(gui_panel=root_con, func=lambda:2, args=[],
               #           text='Continue Game', topleft=(bx, bys[2]), width=b_width, height=6, color=libtcod.light_grey, hcolor=libtcod.white, do_draw_box=True),
               gui.Button(gui_panel=root_con, func=g.game.switch_to_quit_game, args=[],
                          text='Quit', topleft=(bx, bys[3]), width=b_width, height=6, color=g.PANEL_FRONT, do_draw_box=True)]

    ## Start looping
    while not libtcod.console_is_window_closed():
        if g.game.quit_game:
            break
        ## Clear the console
        libtcod.console_clear(root_con.con)

        # Handle buttons
        for button in buttons:
            button.display(mouse)

        #show the title
        #libtcod.console_set_default_foreground(0, libtcod.light_grey)
        libtcod.console_print_ex(0, int(round(g.SCREEN_WIDTH / 2)), int(round(g.SCREEN_HEIGHT / 4)), libtcod.BKGND_NONE, libtcod.CENTER, 'I R O N   T E S T A M E N T')
        libtcod.console_print_ex(0, int(round(g.SCREEN_WIDTH / 2)), int(round(g.SCREEN_HEIGHT) - 2), libtcod.BKGND_NONE, libtcod.CENTER, 'By Josh Coppola - (thanks to Jotaf\'s tutorial!)')

        # Flush console
        libtcod.console_flush()

        event = libtcod.sys_check_for_event(libtcod.EVENT_KEY_PRESS | libtcod.EVENT_MOUSE, key, mouse)




##### START GAME #####
if __name__ == '__main__':

    g.init()

    # spritesheet = 't12_test.png' if g.TILE_SIZE == 12 else 't16_exp2.png'
    spritesheet = 't12_test.png' if g.TILE_SIZE == 12 else 'cp437-thin-8x16_inverted_doubled_mega.png'
    font_path = os.path.join(os.getcwd(), 'fonts', spritesheet)

    # libtcod.console_set_custom_font(font_path, libtcod.FONT_LAYOUT_ASCII_INROW|libtcod.FONT_TYPE_GREYSCALE, 16, 20)
    libtcod.console_set_custom_font(font_path, libtcod.FONT_LAYOUT_ASCII_INROW|libtcod.FONT_TYPE_GREYSCALE, 32, 64)
    libtcod.console_init_root(g.SCREEN_WIDTH, g.SCREEN_HEIGHT, 'Iron Testament v0.5', True, renderer=libtcod.RENDERER_GLSL)
    libtcod.mouse_show_cursor(visible=1)
    libtcod.sys_set_fps(g.LIMIT_FPS)

    # PlayerInterface class has been initialized in GUI
    interface = gui.PlayerInterface()

    root_con = gui.GuiPanel(width=g.SCREEN_WIDTH, height=g.SCREEN_HEIGHT, xoff=0, yoff=0, interface=interface, is_root=1, name='Root', append_to_panels=0)
    map_con = gui.GuiPanel(width=g.CAMERA_WIDTH, height=g.CAMERA_HEIGHT, xoff=0, yoff=0, interface=interface, name='MapCon', append_to_panels=0)
    ## Other GUI panels ##
    panel1 = gui.GuiPanel(width=g.PANEL1_WIDTH, height=g.PANEL1_HEIGHT, xoff=g.PANEL1_XPOS, yoff=g.PANEL1_YPOS, interface=interface, name='Panel1')
    panel2 = gui.GuiPanel(width=g.PANEL2_WIDTH, height=g.PANEL2_HEIGHT, xoff=g.PANEL2_XPOS, yoff=g.PANEL2_YPOS, interface=interface, name='Panel2')
    panel3 = gui.GuiPanel(width=g.PANEL3_WIDTH, height=g.PANEL3_HEIGHT, xoff=g.PANEL3_XPOS, yoff=g.PANEL3_YPOS, interface=interface, name='Panel3')
    panel4 = gui.GuiPanel(width=g.PANEL4_WIDTH, height=g.PANEL4_HEIGHT, xoff=g.PANEL4_XPOS, yoff=g.PANEL4_YPOS, interface=interface, name='Panel4')
    panel4.render = False


    render_handler = RenderHandler()

    #interface.gui_panels = [panel1, panel2, panel3, panel4]
    interface.set_root_panel(root_con)
    interface.set_map_panel(map_con)


    g.game = Game(interface, render_handler)

    data.import_data()

    main_menu()
    #prof.run('main_menu()', 'itstats')
    #p = pstats.Stats('itstats')
    #p.sort_stats('cumulative').print_stats(20)
    #print ''
    #print ' ------ '
    #print ''
    #p.sort_stats('time').print_stats(20)

    libtcod.console_delete(None)
