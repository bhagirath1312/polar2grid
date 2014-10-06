#!/usr/bin/env python
# encoding: utf-8
# Copyright (C) 2014 Space Science and Engineering Center (SSEC),
# University of Wisconsin-Madison.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# This file is part of the polar2grid software package. Polar2grid takes
# satellite observation data, remaps it, and writes it to a file format for
#     input into another program.
# Documentation: http://www.ssec.wisc.edu/software/polar2grid/
#
# Written by David Hoese    September 2014
# University of Wisconsin-Madison
# Space Science and Engineering Center
# 1225 West Dayton Street
# Madison, WI  53706
# david.hoese@ssec.wisc.edu
"""Classes for metadata operations in polar2grid.

:author:       David Hoese (davidh)
:contact:      david.hoese@ssec.wisc.edu
:organization: Space Science and Engineering Center (SSEC)
:copyright:    Copyright (c) 2014 University of Wisconsin SSEC. All rights reserved.
:date:         Sept 2014
:license:      GNU GPLv3

"""
__docformat__ = "restructuredtext en"

import numpy
from polar2grid.core.time_utils import iso8601
from polar2grid.core.dtype import str_to_dtype, dtype_to_str

import os
import sys
import json
import shutil
import logging
from datetime import datetime

LOG = logging.getLogger(__name__)


# FUTURE: Add a register function to register custom P2G objects so no imports and short __class__ names
# FUTURE: Handling duplicate sub-objects better (ex. geolocation)
class P2GJSONDecoder(json.JSONDecoder):
    def __init__(self, *args, **kargs):
        super(P2GJSONDecoder, self).__init__(object_hook=self.dict_to_object, *args, **kargs)

    @staticmethod
    def _jsonclass_to_pyclass(json_class_name):
        import importlib
        cls_name = json_class_name.split(".")[-1]
        mod_name = ".".join(json_class_name.split(".")[:-1])
        if not mod_name:
            try:
                cls = globals()[cls_name]
            except KeyError:
                LOG.error("Unknown class in JSON file: %s", json_class_name)
        else:
            cls = getattr(importlib.import_module(mod_name), cls_name)
        return cls

    def dict_to_object(self, obj):
        for k, v in obj.items():
            if isinstance(v, (str, unicode)):
                try:
                    obj[k] = iso8601(v)
                    continue
                except ValueError:
                    pass

                try:
                    str_to_dtype, dtype_to_str
                    continue
                except KeyError:
                    pass

        if "__class__" not in obj:
            LOG.warning("No '__class__' element in JSON file. Using BaseP2GObject by default.")
            return BaseP2GObject(**obj)

        cls = self._jsonclass_to_pyclass(obj["__class__"])
        inst = cls(**obj)
        return inst


class P2GJSONEncoder(json.JSONEncoder):

    def iterencode(self, o, _one_shot=False):
        """Taken from:
        http://stackoverflow.com/questions/16405969/how-to-change-json-encoding-behaviour-for-serializable-python-object

        Most of the original method has been left untouched.

        _one_shot is forced to False to prevent c_make_encoder from
        being used. c_make_encoder is a funcion defined in C, so it's easier
        to avoid using it than overriding/redefining it.

        The keyword argument isinstance for _make_iterencode has been set
        to self.isinstance. This allows for a custom isinstance function
        to be defined, which can be used to defer the serialization of custom
        objects to the default method.
        """
        # Force the use of _make_iterencode instead of c_make_encoder
        _one_shot = False

        if self.check_circular:
            markers = {}
        else:
            markers = None
        if self.ensure_ascii:
            _encoder = json.encoder.encode_basestring_ascii
        else:
            _encoder = json.encoder.encode_basestring
        if self.encoding != 'utf-8':
            def _encoder(o, _orig_encoder=_encoder, _encoding=self.encoding):
                if isinstance(o, str):
                    o = o.decode(_encoding)
                return _orig_encoder(o)

        def floatstr(o, allow_nan=self.allow_nan,
                     _repr=json.encoder.FLOAT_REPR, _inf=json.encoder.INFINITY, _neginf=-json.encoder.INFINITY):
            if o != o:
                text = 'NaN'
            elif o == _inf:
                text = 'Infinity'
            elif o == _neginf:
                text = '-Infinity'
            else:
                return _repr(o)

            if not allow_nan:
                raise ValueError(
                    "Out of range float values are not JSON compliant: " +
                    repr(o))

            return text

        # Instead of forcing _one_shot to False, you can also just
        # remove the first part of this conditional statement and only
        # call _make_iterencode
        if (_one_shot and json.encoder.c_make_encoder is not None
                and self.indent is None and not self.sort_keys):
            _iterencode = json.encoder.c_make_encoder(
                markers, self.default, _encoder, self.indent,
                self.key_separator, self.item_separator, self.sort_keys,
                self.skipkeys, self.allow_nan)
        else:
            _iterencode = json.encoder._make_iterencode(
                markers, self.default, _encoder, self.indent, floatstr,
                self.key_separator, self.item_separator, self.sort_keys,
                self.skipkeys, _one_shot, isinstance=self.isinstance)
        return _iterencode(o, 0)

    def isinstance(self, obj, cls):
        if isinstance(obj, BaseP2GObject):
            return False
        return isinstance(obj, cls)

    def default(self, obj):
        if isinstance(obj, BaseP2GObject):
            mod_str = str(obj.__class__.__module__)
            mod_str = mod_str + "." if mod_str != __name__ else ""
            cls_str = str(obj.__class__.__name__)
            obj = obj.copy()
            # object should now be a builtin dict
            obj["__class__"] = mod_str + cls_str
            return obj
            # return super(P2GJSONEncoder, self).encode(obj)
        elif isinstance(obj, datetime):
            return obj.isoformat()
        elif numpy.issubclass_(obj, numpy.number):
            return dtype_to_str(obj)
        else:
            return super(P2GJSONEncoder, self).default(obj)


class BaseP2GObject(dict):
    """Base object for all Polar2Grid dictionary-like objects.

    :var _required_kwargs: Keys that must exist when loading an object from a JSON file
    :var _loadable_kwargs: Keys that may be P2G objects saved on disk and should be loaded on creation.
    :var _cleanup_kwargs: Keys that may be saved files on disk (*not* P2G dict-like objects) and should be removed

    """
    _required_kwargs = tuple()
    _loadable_kwargs = tuple()
    _cleanup_kwargs = tuple()

    def __init__(self, *args, **kwargs):
        if kwargs.pop("__class__", None):
            # this is being loaded from a serialized/JSON copy
            # we don't have the 'right' to delete any binary files associated with it
            self.set_persist(True)
            self.validate_keys(kwargs)
        else:
            self.set_persist(False)

        super(BaseP2GObject, self).__init__(*args, **kwargs)

        self.load_loadable_kwargs()

    def __del__(self):
        self.cleanup()

    def cleanup(self):
        """Delete any files associated with this object.
        """
        for kw in self._cleanup_kwargs:
            if kw in self and isinstance(self[kw], (str, unicode)):
                # Do we not want to delete this file because someone tried to save the state of this object
                if hasattr(self, "persist") and not self.persist:
                    try:
                        LOG.info("Removing associated file that is no longer needed: '%s'", self[kw])
                        os.remove(self[kw])
                    except StandardError as e:
                        if hasattr(e, "errno") and e.errno == 2:
                            LOG.debug("Unable to remove file because it doesn't exist: '%s'", self[kw])
                        else:
                            LOG.warning("Unable to remove file: '%s'", self[kw])
                            LOG.debug("Unable to remove file traceback:", exc_info=True)

    def set_persist(self, persist=True):
        """Set the object to keep associated files on disk even after it has been garbage collected.

        :param persist: Whether to persist or not (True by default)

        """
        self.persist = persist
        for child_key, child in self.items():
            if isinstance(child, BaseP2GObject):
                LOG.debug("Setting persist to %s for child '%s'", str(persist), child_key)
                child.set_persist(persist=persist)

    def validate_keys(self, kwargs):
        # sanity check, does this dictionary have everything the class expects it to
        for k in self._required_kwargs:
            if k not in kwargs:
                raise ValueError("Missing required keyword '%s'" % (k,))

    def load_loadable_kwargs(self):
        for kw in self._loadable_kwargs:
            if kw in self and isinstance(self[kw], (str, unicode)):
                LOG.debug("Loading associated JSON file: '%s'", self[kw])
                self[kw] = SwathProduct.load(self[kw])

    @classmethod
    def load(cls, filename):
        """Open a JSON file representing a Polar2Grid object.
        """
        inst = json.load(open(filename, "r"), cls=P2GJSONDecoder)
        return inst

    def save(self, filename):
        """Write the JSON representation of this class to a file.
        """
        f = open(filename, "w")
        try:
            json.dump(self, f, cls=P2GJSONEncoder, indent=4, sort_keys=True)
            self.set_persist()
            self.persist = True
        except TypeError:
            LOG.error("Could not write P2G object to JSON file: '%s'", filename, exc_info=True)
            f.close()
            os.remove(filename)
            raise

    def dumps(self, persist=False):
        """Return a JSON string version of the object.

        :param persist: If True, change 'persist' attribute of object so files already on disk don't get deleted
        """
        if persist:
            self.set_persist()
        return json.dumps(self, cls=P2GJSONEncoder, indent=4, sort_keys=True)


class BaseScene(BaseP2GObject):
    """Base scene class mapping product name to product metadata object.
    """
    def get_fill_value(self, products=None):
        """Get the fill value shared by the products specified (all products by default).
        """
        products = products or self.keys()
        fills = [self[product].get("fill_value", numpy.nan) for product in products]
        if numpy.isnan(fills[0]):
            fills_same = numpy.isnan(fills).all()
        else:
            fills_same = [f == fills[0] for f in fills].all()
        if not fills_same:
            raise RuntimeError("Scene's products don't all share the same fill value")
        return fills[0]

    def get_begin_time(self):
        """Get the begin time shared by all products in the scene.
        """
        products = self.keys()
        return self[products[0]]["begin_time"]

    def get_end_time(self):
        """Get the end time shared by all products in the scene.
        """
        products = self.keys()
        return self[products[0]]["end_time"]


class SwathScene(BaseScene):
    """Container for `SwathProduct` objects.

    Products in a `SwathScene` use latitude and longitude coordinates to define their pixel locations. These pixels
    are typically not on a uniform grid. Products in a `SwathScene` are observed at the same times and over the
    same geographic area, but may be measured or displayed at varying resolutions. The common use case for a
    `SwathScene` is for swaths extracted from satellite imagery files.

    .. note::

        When stored on disk as a JSON file, a `SwathScene's` values may be filenames of a saved `SwathProduct` object.

    .. seealso::

        `GriddedScene`: Scene object for gridded products.

    """
    pass


class GriddedScene(BaseScene):
    """Container for `GriddedProduct` objects.

    Products in a `GriddedScene` are mapped to a uniform grid specified by a projection, grid size, grid origin,
    and pixel size. All products in a `GriddedScene` should use the same grid.

    .. note::

        When stored on disk as a JSON file, a `GriddedScene's` values may be filenames of a saved `GriddedProduct`
        object.

    .. seealso::

        `SwathScene`: Scene object for geographic longitude/latitude products.

    """
    pass


class BaseProduct(BaseP2GObject):
    """Base product class for storing metadata.
    """
    def get_data_array(self, item, rows, cols, dtype):
        """Get FBF item as a numpy array.

        File is loaded from disk as a memory mapped file if needed.
        """
        data = self[item]
        if isinstance(data, (str, unicode)):
            # load FBF data from a file if needed
            data = numpy.memmap(data, dtype=dtype, shape=(rows, cols), mode="r")

        return data

    def get_data_mask(self, item, fill=numpy.nan, fill_key=None):
        """Return a boolean mask where the data for `item` is invalid/bad.
        """
        data = self.get_data_array(item)

        if fill_key is not None:
            fill = self[fill_key]

        if numpy.isnan(fill):
            return numpy.isnan(data)
        else:
            return data == fill

    def copy_array(self, item, rows, cols, dtype, filename=None, read_only=True):
        """Copy the array item of this swath.

        If the `filename` keyword is passed the data will be written to that file. The copy returned
        will be a memory map. If `read_only` is False, the memory map will be opened with mode "r+".

        The 'read_only' keyword is ignored if `filename` is None.
        """
        mode = "r" if read_only else "r+"
        data = self[item]

        if isinstance(data, (str, unicode)):
            # we have a binary filename
            if filename:
                # the user wants to copy the FBF
                shutil.copyfile(data, filename)
                data = filename
                return numpy.memmap(data, dtype=dtype, shape=(rows, cols), mode=mode)
            if mode == "r":
                return numpy.memmap(data, dtype=dtype, shape=(rows, cols), mode="r")
            else:
                return numpy.memmap(data, dtype=dtype, shape=(rows, cols), mode="r").copy()
        else:
            if filename:
                data.tofile(filename)
                return numpy.memmap(filename, dtype=dtype, shape=(rows, cols), mode=mode)
            return data.copy()


class SwathProduct(BaseProduct):
    """Swath product class for image products geolocated using longitude and latitude points.

    Required Information:
        - product_name (string): Name of the product this swath represents
        - satellite (string): Name of the satellite the data came from
        - instrument (string): Name of the instrument on the satellite from which the data was observed
        - begin_time (datetime): Datetime object representing the best known start of observation for this product's data
        - end_time (datetime): Datetime object representing the best known end of observation for this product's data
        - longitude (product object): Longitude `SwathProduct`, may be 'None' inside Longitude object
        - latitude (product object): Latitude `SwathProduct`, may be 'None' inside Latitude object
        - swath_rows (int): Number of rows in the main 2D data array
        - swath_columns (int): Number of columns in the main 2D data array
        - data_type (numpy.dtype): Data type of image data or if on disk on of (real4, int1, uint1, etc)
        - swath_data (array): Binary filename or numpy array for the main data array

    Optional Information:
        - description (string): Basic description of the product (empty string by default)
        - source_filenames (list of strings): Unordered list of source files that made up this product ([] by default)
        - data_kind (string): Name for the type of the measurement (ex. btemp, reflectance, radiance, etc.)
        - rows_per_scan (int): Number of swath rows making up one scan of the sensor (0 if not applicable or not specified)
        - units (string): Image data units (empty string by default)
        - fill_value: Missing data value in 'swath_data' (defaults to `numpy.nan` if not present)
        - nadir_resolution (float): Size in meters of instrument's nadir footprint/pixel
        - edge_resolution (float): Size in meters of instrument's edge footprint/pixel

    .. note::

        When datetime objects are written to disk as JSON they are converted to ISO8601 strings.

    .. seealso::

        `GriddedProduct`: Product object for gridded products.

    """
    # Validate required keys when loaded from disk
    _required_kwargs = (
        "product_name",
        "satellite",
        "instrument",
        "begin_time",
        "end_time",
        "longitude",
        "latitude",
        "swath_rows",
        "swath_columns",
        "data_type",
        "swath_data",
    )

    _loadable_kwargs = (
        "longitude",
        "latitude",
    )

    _cleanup_kwargs = (
        "swath_data",
    )

    def __init__(self, *args, **kwargs):
        super(SwathProduct, self).__init__(*args, **kwargs)

    def get_data_array(self, item):
        """Get FBF item as a numpy array.

        File is loaded from disk as a memory mapped file if needed.
        """
        dtype = str_to_dtype(self["data_type"])
        rows = self["swath_rows"]
        cols = self["swath_columns"]
        return super(SwathProduct, self).get_data_array(item, rows, cols, dtype)

    def get_data_mask(self, item):
        return super(SwathProduct, self).get_data_mask(item, fill_key="fill_value")

    def copy_array(self, item, filename=None, read_only=True):
        """Copy the array item of this swath.

        If the `filename` keyword is passed the data will be written to that file. The copy returned
        will be a memory map. If `read_only` is False, the memory map will be opened with mode "r+".

        The 'read_only' keyword is ignored if `filename` is None.
        """
        dtype = str_to_dtype(self["data_type"])
        rows = self["swath_rows"]
        cols = self["swath_columns"]
        return super(SwathProduct, self).copy_array(item, rows, cols, dtype, filename, read_only)


class GriddedProduct(BaseProduct):
    """Gridded product class for image products on a uniform, projected grid.

    Required Information:
        - product_name: Name of the product this swath represents
        - satellite: Name of the satellite the data came from
        - instrument: Name of the instrument on the satellite from which the data was observed
        - begin_time: Datetime object representing the best known start of observation for this product's data
        - end_time: Datetime object represnting the best known end of observation for this product's data
        - data_type (string): Data type of image data (real4, uint1, int1, etc)
        - grid_data: Binary filename or numpy array for the main data array

    Optional Information:
        - description (string): Basic description of the product (empty string by default)
        - source_filenames (list of strings): Unordered list of source files that made up this product ([] by default)
        - data_kind (string): Name for the type of the measurement (ex. btemp, reflectance, radiance, etc.)
        - rows_per_scan (int): Number of swath rows making up one scan of the sensor (0 if not applicable or not specified)
        - fill_value: Missing data value in 'swath_data' (defaults to `numpy.nan` if not present)

    .. seealso::

        `SwathProduct`: Product object for products using longitude and latitude for geolocation.

    """
    # Validate required keys when loaded from disk
    _required_kwargs = (
        "product_name",
        "satellite",
        "instrument",
        "begin_time",
        "end_time",
        "grid_definition",
        "grid_data",
    )

    _cleanup_kwargs = (
        "grid_data",
    )

    def from_swath_product(self, swath_product):
        for k in ["product_name", "satellite", "instrument", "begin_time", "end_time", "data_type"]:
            self[k] = swath_product[k]

    def get_data_array(self, item):
        """Get FBF item as a numpy array.

        File is loaded from disk as a memory mapped file if needed.
        """
        dtype = str_to_dtype(self["data_type"])
        rows = self["grid_definition"]["height"]
        cols = self["grid_definition"]["width"]
        return super(GriddedProduct, self).get_data_array(item, rows, cols, dtype)

    def get_data_mask(self, item):
        return super(GriddedProduct, self).get_data_mask(item, fill_key="fill_value")

    def copy_array(self, item, filename=None, read_only=True):
        """Copy the array item of this swath.

        If the `filename` keyword is passed the data will be written to that file. The copy returned
        will be a memory map. If `read_only` is False, the memory map will be opened with mode "r+".

        The 'read_only' keyword is ignored if `filename` is None.
        """
        dtype = str_to_dtype(self["data_type"])
        rows = self["grid_definition"]["height"]
        cols = self["grid_definition"]["width"]
        return super(GriddedProduct, self).copy_array(item, rows, cols, dtype, filename, read_only)


class GridDefinition(BaseP2GObject):
    """Projected grid defined by a PROJ.4 projection string and other grid parameters.

    Required Information:
        - name: Identifying name for the grid
        - proj4_definition (string): PROJ.4 projection definition
        - height: Height of the grid in number of pixels
        - width: Width of the grid in number of pixels
        - cell_height: Grid cell height in the projection domain (usually in meters or degrees)
        - cell_width: Grid cell width in the projection domain (usually in meters or degrees)
        - origin_x: X-coordinate of the upper-left corner of the grid in the projection domain
        - origin_y: Y-coordinate of the upper-left corner of the grid in the projection domain
    """
    _required_kwargs = (
        "grid_name",
        "proj4_definition",
        "height",
        "width",
        "cell_height",
        "cell_width",
        "origin_x",
        "origin_y",
    )

    @property
    def is_static(self):
        return all([self[x] is not None for x in [
            "height", "width", "cell_height", "cell_width", "origin_x", "origin_y"
        ]])
