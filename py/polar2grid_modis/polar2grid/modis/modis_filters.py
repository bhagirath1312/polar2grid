#!/usr/bin/env python
# encoding: utf-8
"""
Filters that operate on MODIS data.
Some of these filters may be generalizable at a future date.

:author:       Eva Schiffer (evas)
:contact:      evas@ssec.wisc.edu
:organization: Space Science and Engineering Center (SSEC)
:copyright:    Copyright (c) 2012 University of Wisconsin SSEC. All rights reserved.
:date:         Nov 2012
:license:      GNU GPLv3
:revision:     $Id$
"""
__docformat__ = "restructuredtext en"

import modis_guidebook
from polar2grid.core.constants import *
from polar2grid.core.constants import DEFAULT_FILL_VALUE
from polar2grid.modis.bt       import bright_shift
from polar2grid.core           import Workspace

import numpy
import os
import sys
import logging
from glob import glob

log = logging.getLogger(__name__)

def _load_data_from_workspace (file_name, file_path='.') :
    """
    Load data from a flat file in a workspace. A copy of the data in the file will be returned.
    
    Note: This method may raise errors if a problem is encountered.
    """
    
    # load up the image data
    try:
        W    = Workspace(file_path)
        temp = getattr(W, file_name)
        data = temp.copy()
        log.debug("Data min: %f, Data max: %f" % (data.min(),data.max()))
    except StandardError:
        log.error("Could not open file %s at path %s" % file_name, file_path)
        log.debug("Files matching %r" % glob(file_name + "*"))
        raise
    
    return data

def _cloud_clear (data, clouds, values_to_clear, data_fill_value=DEFAULT_FILL_VALUE) :
    """
    Given data and associated cloud data, clear the parts of the data that correspond to the parts of
    the cloud data with the values in values_to_clear. Cleared values will be filled
    with data_fill_value.
    
    A copy of data with the clouds cleared will be returned.
    
    Note: data and clouds are expected to be numpy arrays.
    """
    
    # make a new copy of the data so we don't mess up the original
    new_data = data.copy()
    
    # where the values we what to clear for appear, clear our data
    for cloud_val in values_to_clear :
        where_mask = clouds == cloud_val
        new_data[where_mask] = data_fill_value
    
    return new_data

def convert_radiance_to_bt (img_filepath, satellite, band_number, fill_value=DEFAULT_FILL_VALUE):
    """Convert a set of radiances to brightness temperatures.

    :Parameters:
        img_filepath : str
            Filepath to get the binary image swath data in FBF format
            (ex. ``image_infrared20.real4.6400.10176``).
        satellite : str
            The constant representing Aqua or Terra. This should
            match the constant SAT_AQUA or SAT_TERRA from the
            core constants.py module
    """
    
    img_file_name = os.path.split(img_filepath)[1]
    img_attr      = img_file_name.split('.')[0]
    
    # load up the image data
    data = _load_data_from_workspace (img_attr)
    
    # This is very suboptimal, FUTURE: find a better way to do this translation
    if satellite is SAT_AQUA :
        satellite = "Aqua"
    if satellite is SAT_TERRA :
        satellite = "Terra"
    
    # calculate the brightness temperatures
    # TODO, I don't know if there are any exceptions I need to catch here
    not_fill_mask           = data != fill_value
    new_data                = data.copy().astype(numpy.float64)
    new_data[not_fill_mask] = bright_shift(satellite, new_data[not_fill_mask], int(band_number))
    new_data                = new_data.astype(numpy.float32)
    new_data[~numpy.isfinite(new_data)] = fill_value
    
    """
    # TEMP, some debug code
    not_fill_mask = new_data != fill_value
    max_temp      = numpy.max(new_data[not_fill_mask])
    min_temp      = numpy.min(new_data[not_fill_mask])
    print ("after bt conversion band " + str(band_number) + " uses fill value " + str(fill_value) + " and has range " + str(min_temp) + " to " + str(max_temp))
    """
    
    # save to a file
    bt_file_path = None
    try :
        bt_file_name = "bt_prescale_%s" % (img_file_name)
        bt_file_path = os.path.join(os.path.split(img_filepath)[0], bt_file_name)
        new_data.tofile(bt_file_path)
    except StandardError:
        log.error("Unexpected error while saving rescaled data")
        log.debug("Rescaling error:", exc_info=1)
        raise
    
    return bt_file_path

def make_data_cloud_cleared (data_fbf_path, clouds_fbf_path, list_of_cloud_values_to_clear,
                             data_fill_value=DEFAULT_FILL_VALUE) :
    """
    Given data and associated cloud data, clear the parts of the data that correspond to the parts of
    the cloud data with the values in list_of_cloud_values_to_clear. Cleared values will be filled
    with data_fill_value.
    """
    
    # parse some file path info
    img_file_name = os.path.split(data_fbf_path)[1]
    img_attr      = img_file_name.split('.')[0]
    cld_file_name = os.path.split(clouds_fbf_path)[1]
    cld_attr      = cld_file_name.split('.')[0]
    
    # load up the data file
    data       = _load_data_from_workspace (img_attr)
    
    # load up the cloud mask data
    cloud_data = _load_data_from_workspace (cld_attr)
    
    # cloud clear the data
    new_data = _cloud_clear (data, cloud_data, list_of_cloud_values_to_clear,
                             data_fill_value=data_fill_value)
    
    # save the cloud cleared data to a file
    new_img_file_name = "cloud_cleared_%s" % (img_file_name)
    new_file_path     = os.path.join(os.path.split(data_fbf_path)[0], new_img_file_name)
    try :
        new_data.tofile(new_img_file_name)
    except StandardError:
        log.error("Unexpected error while saving cloud cleared data")
        log.debug("Cloud clearing error:", exc_info=1)
        raise
    
    return new_file_path

def create_fog_band (band_20_bt_meta_data, band_31_bt_meta_data, fog_fill_value=DEFAULT_FILL_VALUE) :
    """
    Given bands 20 and 31 as brightness temperatures, create the fog band, with associcated flat binary file and meta data.
    
    Return the appropriate meta data dictionary for fog.
    """
    
    # get some information out of the meta data
    band_20_bt_fbf_path = band_20_bt_meta_data["fbf_swath"] if "fbf_swath" in band_20_bt_meta_data else band_20_bt_meta_data["fbf_img"]
    band_31_bt_fbf_path = band_31_bt_meta_data["fbf_swath"] if "fbf_swath" in band_31_bt_meta_data else band_31_bt_meta_data["fbf_img"]
    band_20_fill_value  = band_20_bt_meta_data["fill_value"]
    band_31_fill_value  = band_31_bt_meta_data["fill_value"]
    
    # parse some file path info
    band_20_file_name = os.path.split(band_20_bt_fbf_path)[1]
    band_20_attr      = band_20_file_name.split('.')[0]
    band_31_file_name = os.path.split(band_31_bt_fbf_path)[1]
    band_31_attr      = band_31_file_name.split('.')[0]
    
    # load the brightness temperature data
    band_20_data = _load_data_from_workspace(band_20_attr)
    band_31_data = _load_data_from_workspace(band_31_attr)
    
    # create the fog data
    fog_data     = band_31_data - band_20_data
    
    # handle the fill values
    fog_data[band_20_data == band_20_fill_value] = fog_fill_value
    fog_data[band_31_data == band_31_fill_value] = fog_fill_value
    
    # save the fog data to disk
    name_suffix = band_31_file_name.split('infrared_31')[1]
    fog_name    = "image_infrared_fog%s" % name_suffix
    fog_file_path = os.path.join(os.path.split(band_20_bt_fbf_path)[0], fog_name)
    try :
        fog_data.tofile(fog_file_path)
    except StandardError :
        log.error("Unexpected error while saving newly created fog data")
        log.debug("Fog creation error:", exc_info=1)
        raise
    
    # build the meta data for fog
    fog_meta_data                  = band_20_bt_meta_data.copy()
    fog_meta_data["data_kind"]     = DKIND_FOG
    fog_meta_data["remap_data_as"] = DKIND_BTEMP
    fog_meta_data["kind"]          = BKIND_IR
    fog_meta_data["band"]          = BID_FOG
    fog_meta_data["fill_value"]    = fog_fill_value
    fog_meta_data["fbf_img"]       = fog_file_path
    
    return fog_meta_data

def main():
    import optparse
    usage = """
%prog [options] filename1.h,filename2.h,filename3.h,... struct1,struct2,struct3,...

"""
    parser = optparse.OptionParser(usage)
    parser.add_option('-t', '--test', dest="self_test",
                    action="store_true", default=False, help="run self-tests")
    parser.add_option('-v', '--verbose', dest='verbosity', action="count", default=0,
                    help='each occurrence increases verbosity 1 level through ERROR-WARNING-INFO-DEBUG')
    # parser.add_option('-o', '--output', dest='output',
    #                 help='location to store output')
    # parser.add_option('-I', '--include-path', dest="includes",
    #                 action="append", help="include path to append to GCCXML call")
    (options, args) = parser.parse_args()

    # make options a globally accessible structure, e.g. OPTS.
    global OPTS
    OPTS = options

    if options.self_test:
        import doctest
        doctest.testmod()
        sys.exit(0)

    levels = [logging.ERROR, logging.WARN, logging.INFO, logging.DEBUG]
    logging.basicConfig(level = levels[min(3, options.verbosity)])

    if not args:
        parser.error( 'incorrect arguments, try -h or --help.' )
        return 9
    
    # FUTURE: add more complex tests here
    
    return 0

if __name__=='__main__':
    sys.exit(main())
