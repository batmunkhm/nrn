from .rxdmath import _Arithmeticed
import weakref
from .section1d import Section1D
from neuron import h, nrn
import rxd
from . import node, nodelist, rxdmath, region
import numpy
import warnings
import itertools
from .rxdException import RxDException
import initializer

# The difference here is that defined species only exists after rxd initialization
_all_species = []
_defined_species = {}
def _get_all_species():
    return _defined_species

_species_count = 0

_has_1d = False
_has_3d = False

def _1d_submatrix_n():
    if not _has_1d:
        return 0
    elif not _has_3d:
        return len(node._states)
    else:
        return numpy.min([sp()._indices3d() for sp in _get_all_species().values() if sp() is not None])
            


class _SpeciesMathable(object):
    # support arithmeticing
    def __neg__(self):
        return -1 * _Arithmeticed(self)
    def __Pos__(self):
        return _Arithmeticed(self)
    def __pow__(self, other):
        return _Arithmeticed(self) ** other
    def __add__(self, other):
        return _Arithmeticed(self) + other
    def __sub__(self, other):
        return _Arithmeticed(self) - other
    def __mul__(self, other):
        return _Arithmeticed(self) * other
    def __div__(self, other):
        return _Arithmeticed(self) / other
    def __radd__(self, other):
        return _Arithmeticed(other) + self
    def __rmul__(self, other):
        return _Arithmeticed(self) * other
    def __rdiv__(self, other):
        return _Arithmeticed(other) / self
    def __rsub__(self, other):
        return _Arithmeticed(other) - self
    def __abs__(self):
        return abs(_Arithmeticed(self))
    
    def _evaluate(self, location):
        return _Arithmeticed(self)._evaluate(location)

    def __ne__(self, other):
        other = rxdmath._ensure_arithmeticed(other)
        self2 = rxdmath._ensure_arithmeticed(self)
        rxdmath._validate_reaction_terms(self2, other)
        return rxdmath._Reaction(self2, other, '<>')
    
    def __gt__(self, other):
        other = rxdmath._ensure_arithmeticed(other)
        self2 = rxdmath._ensure_arithmeticed(self)
        rxdmath._validate_reaction_terms(self2, other)
        return rxdmath._Reaction(self2, other, '>')

    def __lt__(self, other):
        other = rxdmath._ensure_arithmeticed(other)
        self2 = rxdmath._ensure_arithmeticed(self)
        rxdmath._validate_reaction_terms(self2, other)
        return rxdmath._Reaction(self2, other, '<')

    @property
    def _semi_compile(self):
        return 'species%d' % (self._id)

    def _involved_species(self, the_dict):
        the_dict[self._semi_compile] = weakref.ref(self)

    @property
    def d(self):
        """diffusion constant. write-only"""
        raise RxDException('diffusion constant is write-only')
    
    @d.setter
    def d(self, value):
        if hasattr(self, '_allow_setting'):
            self._d = value
        else:
            _volumes, _surface_area, _diffs = node._get_data()
            _diffs[self.indices()] = value
            rxd._setup_matrices()

class SpeciesOnRegion(_SpeciesMathable):
    def __init__(self, species, region):
        """The restriction of a Species to a Region."""
        global _species_count
        self._species = weakref.ref(species)
        self._region = weakref.ref(region)
        self._id = _species_count
        _species_count += 1
        
    def __eq__(self, other):
        """test for equality.
        
        Two SpeciesOnRegion objects are equal if they refer to the same species
        on the same region and both the species and the region still exist.
        """
        return (self._species() == other._species()) and (self._region() == other._region()) and (self._species() is not None) and (self._region() is not None)
    
    def __hash__(self):
        return 1000 * (hash(self._species()) % 1000) + (hash(self._region()) % 1000)
    
    
    def __repr__(self):
        return '%r[%r]' % (self._species(), self._region())

    def indices(self, r=None):
        """If no Region is specified or if r is the Region specified in the constructor,
        returns a list of the indices of state variables corresponding
        to the Species when restricted to the Region defined in the constructor.

        If r is a different Region, then returns the empty list.
        """    
        #if r is not None and r != self._region():
        #    raise RxDException('attempt to access indices on the wrong region')
        # TODO: add a mechanism to catch if not right region (but beware of reactions crossing regions)
        if self._species() is None or self._region() is None:
            return []
        return self._species().indices(self._region())
    

    def __getitem__(self, r):
        """Return a reference to those members of this species lying on the specific region @varregion.
        The resulting object is a SpeciesOnRegion.
        This is useful for defining reaction schemes for MultiCompartmentReaction.
        
        This is provided to allow use of SpeciesOnRegion where Species would normally go.
        
        If the regions match, self is returned; otherwise an empty SpeciesOnRegion.
        """
        if r == self._region():
            return self
        else:
            return SpeciesOnRegion(self._species, None)
    
    @property
    def states(self):
        """A vector of all the states corresponding to this species"""
        all_states = node._get_states()
        return [all_states[i] for i in numpy.sort(self.indices())]
    
    @property
    def nodes(self):
        """A NodeList of the Node objects containing concentration data for the given Species and Region.

        The code

            node_list = ca[cyt].nodes

        is more efficient than the otherwise equivalent

            node_list = ca.nodes(cyt)

        because the former only creates the Node objects belonging to the restriction ca[cyt] whereas the second option
        constructs all Node objects belonging to the Species ca and then culls the list to only include those also
        belonging to the Region cyt.
        """
        return nodelist.NodeList(itertools.chain.from_iterable([s.nodes for s in self._species()._secs if s._region == self._region()]))
    
    @property
    def concentration(self):
        """An iterable of the current concentrations."""
        return self.nodes.concentration
    
    @concentration.setter
    def concentration(self, value):
        """Sets all Node objects in the restriction to the specified concentration value.
        
        This is equivalent to s.nodes.concentration = value"""
        self.nodes.concentration = value


# 3d matrix stuff
def _setup_matrices_process_neighbors(pt1, pt2, indices, euler_matrix, index, diffs, vol, areal, arear, dx):
    d = diffs[index]
    if pt1 in indices:
        ileft = indices[pt1]
        dleft = (d + diffs[ileft]) * 0.5
        left = dleft * areal / (vol * dx)
        euler_matrix[index, ileft] += left
        euler_matrix[index, index] -= left
    if pt2 in indices:
        iright = indices[pt2]
        dright = (d + diffs[iright]) * 0.5
        right = dright * arear / (vol * dx)
        euler_matrix[index, iright] += right
        euler_matrix[index, index] -= right




# TODO: make sure that we can make this work where things diffuse across the
#       boundary between two regions... for the tree solver, this is complicated
#       because need the sections in a sorted order
#       ... but this is also weird syntactically, because how should it know
#       that two regions (e.g. apical and other_dendrites) are connected?

class Species(_SpeciesMathable):
    def __init__(self, regions=None, d=0, name=None, charge=0, initial=None):
        """s = rxd.Species(regions, d = 0, name = None, charge = 0, initial = None)
    
        Declare a species.

        Parameters:

        regions -- a Region or list of Region objects containing the species

        d -- the diffusion constant of the species (optional; default is 0, i.e. non-diffusing)

        name -- the name of the Species; used for syncing with HOC (optional; default is none)

        charge -- the charge of the Species (optional; default is 0)

        initial -- the initial concentration or None (if None, then imports from HOC if the species is defined at finitialize, else 0)


        Note:

        charge must match the charges specified in NMODL files for the same ion, if any."""

        # TODO: check if "name" already defined elsewhere (if non-None)
        #       if so, make sure other fields consistent, expand regions as appropriate

        self._allow_setting = True
        self.regions = regions
        self.d = d
        self.name = name
        self.charge = charge
        self.initial = initial
        _all_species.append(weakref.ref(self))

        # initialize self if the rest of rxd is already initialized
        if initializer.is_initialized():
            if _has_3d:
                # TODO: remove this limitation
                #       it's especially not a problem if the new stuff is 3D
                raise RxDException('temporarily cannot add new species after rxd is initialized because 1D and 3D blocks need to be kept together')
            self._do_init()
    
    def _do_init(self):
        self._do_init1()
        self._do_init2()
        self._do_init3()
        self._do_init4()
        
    def _do_init1(self):
        # TODO: if a list of sections is passed in, make that one region
        # _species_count is used to create a unique _real_name for the species
        global _species_count


        regions = self._regions
        self._real_name = self._name
        initial = self.initial
        charge = self._charge
        
        # invalidate any old initialization of external solvers
        rxd._external_solver_initialized = False
        
        # TODO: check about the 0<x<1 problem alluded to in the documentation
        h.define_shape()
        name = self.name
        if name is not None:
            if not isinstance(name, str):
                raise RxDException('Species name must be a string')
            if name in _defined_species and _defined_species[name]() is not None:
                raise RxDException('Species "%s" previously defined: %r' % (name, _defined_species[name]()))
        else:
            name = _species_count
        self._id = _species_count
        _species_count += 1
        _defined_species[name] = weakref.ref(self)
        if regions is None:
            raise RxDException('Must specify region where species is present')
        if hasattr(regions, '__len__'):
            regions = list(regions)
        else:
            regions = list([regions])
        self._regions = regions
        if not all(isinstance(r, region.Region) for r in regions):
            raise RxDException('regions list must consist of Region objects only')
        self._species = weakref.ref(self)        
        # at this point self._name is None if unnamed or a string == name if
        # named
        self._ion_register()                     
        
        # TODO: remove this line when certain no longer need it (commented out 2013-04-17)
        # self._real_secs = region._sort_secs(sum([r.secs for r in regions], []))
    
    def _do_init2(self):
        # 1D section objects; NOT all sections this species lives on
        # TODO: this may be a problem... debug thoroughly
        global _has_1d
        d = self._d
        self._secs = [Section1D(self, sec, d, r) for r in self._regions for sec in r._secs1d]
        if self._secs:
            self._offset = self._secs[0]._offset
            _has_1d = True
        else:
            self._offset = 0

    def _do_init3(self):
        global _has_3d
        # 3D sections
       
        # NOTE: if no 3D nodes, then _3doffset is not meaningful
        self._3doffset = 0
        self._nodes = []
        if self._regions:
            r = self._regions[0]
            if r._secs3d:
                if len(self._regions) != 1:
                    raise RxDException('3d currently only supports 1 region per species')
                selfref = weakref.ref(self)
                xs, ys, zs, segs = r._xs, r._ys, r._zs, r._segs
                self._3doffset = node._allocate(len(xs))
                for i, x, y, z, seg in zip(xrange(len(xs)), xs, ys, zs, segs):
                    self._nodes.append(node.Node3D(i + self._3doffset, x, y, z, r, seg, selfref))
                # the region is now responsible for computing the correct volumes and surface areas
                    # this is done so that multiple species can use the same region without recomputing it
                node._volumes[range(self._3doffset, self._3doffset + len(xs))] = r._vol
                node._surface_area[self._3doffset : self._3doffset + len(xs)] = r._sa
                node._diffs[range(self._3doffset, self._3doffset + len(xs))] = self._d
                _has_3d = True

    def _do_init4(self):
        # final initialization        
        self._has_adjusted_offsets = False
        self._assign_parents()
        for sec in self._secs:
            # NOTE: can only init_diffusion_rates after the roots (parents)
            #       have been assigned
            sec._init_diffusion_rates()
        self._update_region_indices()
        
        self._register_cptrs()


    def _ion_register(self):
        charge = self._charge
        if self._name is not None:
            ion_type = h.ion_register(self._name, charge)
            if ion_type == -1:
                raise RxDException('Unable to register species: %s' % self._name)
            # insert the species if not already present
            regions = self._regions if hasattr(self._regions, '__len__') else [self._regions]
            for r in regions:
                if r.nrn_region in ('i', 'o'):
                    for s in r.secs:
                        try:
                            ion_forms = [self._name + 'i', self._name + 'o', 'i' + self._name, 'e' + self._name]
                            for i in ion_forms:
                                # this throws an exception if one of the ion forms is missing
                                temp = s.__getattribute__(self._name + 'i')
                        except:
                            s.insert(self._name + '_ion')
                        # set to recalculate reversal potential automatically
                        # the last 1 says to set based on global initial concentrations
                        # e.g. nai0_na_ion, etc...
                        h.ion_style(self._name + '_ion', 3, 2, 1, 1, 1, sec=s)

    @property
    def states(self):
        """A vector of all the states corresponding to this species"""
        all_states = node._get_states()
        return [all_states[i] for i in numpy.sort(self.indices())]


    def _setup_matrices3d(self, euler_matrix):
        # TODO: this doesn't handle multiple regions
        region_mesh = self._regions[0]._mesh.values
        indices = {}
        xs, ys, zs = region_mesh.nonzero()
        diffs = node._diffs
        for i in xrange(len(xs)):
            indices[(xs[i], ys[i], zs[i])] = i
        dx = self._regions[0]._dx
        areal = dx * dx
        arear = dx * dx
        for nodeobj in self._nodes:
            i, j, k, index, vol = nodeobj._i, nodeobj._j, nodeobj._k, nodeobj._index, nodeobj.volume
            _setup_matrices_process_neighbors((i, j, k - 1), (i, j, k + 1), indices, euler_matrix, index, diffs, vol, areal, arear, dx)
            _setup_matrices_process_neighbors((i, j - 1, k), (i, j + 1, k), indices, euler_matrix, index, diffs, vol, areal, arear, dx)
            _setup_matrices_process_neighbors((i - 1, j, k), (i + 1, j, k), indices, euler_matrix, index, diffs, vol, areal, arear, dx)
            


    def re_init(self):
        """Reinitialize the rxd concentration of this species to match the NEURON grid"""
        self._import_concentration(init=False)

    def __getitem__(self, r):
        """Return a reference to those members of this species lying on the specific region @varregion.
        The resulting object is a SpeciesOnRegion.
        This is useful for defining reaction schemes for MultiCompartmentReaction."""
        return SpeciesOnRegion(self, r)

    def _update_node_data(self):
        for sec in self._secs:
            sec._update_node_data()
            
    def concentrations(self):
        if self._secs:
            raise RxDException('concentrations only supports 3d and that is deprecated')
        warnings.warn('concentrations is deprecated; do not use')
        r = self._regions[0]
        data = numpy.array(r._mesh.values, dtype=float)
        # things outside of the volume will be NaN
        data[:] = numpy.NAN
        max_concentration = -1
        for node in self.nodes:
            data[node._i, node._j, node._k] = node.concentration
        return data
        

    def _register_cptrs(self):
        # 1D stuff
        for sec in self._secs:
            sec._register_cptrs()
        # 3D stuff
        if self._nodes:
            assert(len(self._regions) == 1)
            r = self._regions[0]
            nrn_region = r._nrn_region
            self._concentration_ptrs = []
            if nrn_region is not None and self.name is not None:
                ion = '_ref_' + self.name + nrn_region
                self._seg_order = r._nodes_by_seg.keys()
                for seg in self._seg_order:
                    self._concentration_ptrs.append(seg.__getattribute__(ion))    

    @property
    def charge(self):
        """Get or set the charge of the Species.
        
        .. note:: Setting is new in NEURON 7.4+ and is allowed only before the reaction-diffusion model is instantiated.
        """
        return self._charge

    @charge.setter
    def charge(self, value):
        if hasattr(self, '_allow_setting'):
            self._charge = value
        else:
            raise RxDException('Cannot set charge now; model already instantiated')

    @property
    def regions(self):
        """Set the regions where the Species is present
        
        .. note:: New in NEURON 7.4+. Setting is allowed only before the reaction-diffusion model is instantiated.
        """
        raise RxDException('regions is write only')

    @regions.setter
    def regions(self, value):
        if hasattr(self, '_allow_setting'):
            self._regions = value
        else:
            raise RxDException('Cannot set regions now; model already instantiated')

        
    def _update_region_indices(self):
        # TODO: should this include 3D nodes? currently 1D only. (What faces the user?)
        self._region_indices = {}
        for s in self._secs:
            if s._region not in self._region_indices:
                self._region_indices[s._region] = []
            self._region_indices[s._region] += s.indices
        # a list of all indices
        self._region_indices[None] = list(itertools.chain.from_iterable(self._region_indices.values()))
    
    def _indices3d(self, r=None):
        """return the indices of just the 3D nodes corresponding to this species in the given region"""
        # TODO: this will need changed if 3D is to support more than one region
        if r is None or r == self._regions[0]:
            return range(self._3doffset, self._3doffset + len(self._nodes))
        else:
            return []

    def _indices1d(self, r=None):
        """return the indices of just the 1D nodes corresponding to this species in the given region"""
        return self._region_indices.get(r, [])
    
    def indices(self, r=None):
        """return the indices corresponding to this species in the given region
        
        if r is None, then returns all species indices"""
        # TODO: beware, may really want self._indices3d or self._indices1d
        initializer._do_init()
        return self._indices1d(r) + self._indices3d(r)
        
    
    def _setup_diffusion_matrix(self, g):
        for s in self._secs:
            s._setup_diffusion_matrix(g)
    
    def _setup_c_matrix(self, c):
        # TODO: this will need to be changed for three dimensions, or stochastic
        for s in self._secs:
            for i in xrange(s._offset, s._offset + s.nseg):
                c[i, i] = 1.
    
    def _setup_currents(self, indices, scales, ptrs, cur_map):
        if self.name:
            cur_map[self.name + 'i'] = {}
            cur_map[self.name + 'o'] = {}
        # 1D part
        for s in self._secs:
            s._setup_currents(indices, scales, ptrs, cur_map)
        # 3D part
        if self._nodes:
            # TODO: this is very similar to the 1d code; merge
            # TODO: this needs changed when supporting more than one region
            assert(len(self._regions) == 1)
            nrn_region = self._regions[0].nrn_region
            if nrn_region is not None and self.name is not None and self.charge != 0:
                ion_curr = '_ref_i%s' % self.name
                volumes, surface_area, diffs = node._get_data()
                # TODO: this implicitly assumes that o and i border the membrane
                # different signs depending on if an outward current decreases the region's concentration or increases it
                if nrn_region == 'i':
                    sign = -1
                elif nrn_region == 'o':
                    sign = 1
                else:
                    raise RxDException('bad nrn_region for setting up currents (should never get here)')
                local_indices = self._indices3d()
                offset = self._offset
                charge = self.charge
                name = '%s%s' % (self.name, nrn_region)
                sign_tenthousand_over_charge_faraday = sign * 10000. / (charge * rxd.FARADAY)
                for i, nodeobj in enumerate(self._nodes):
                    if surface_area[i]:
                        seg = nodeobj.segment
                        cur_map[name][seg] = len(indices)
                        indices.append(local_indices[i])
                        if volumes[i + offset] == 0:
                            print '0 volume at position %d; surface area there: %g' % (i + offset, surface_area[i + offset])
                        scales.append(sign_tenthousand_over_charge_faraday * surface_area[i + offset] / volumes[i + offset])
                        ptrs.append(seg.__getattribute__(ion_curr))

    
    def _has_region_section(self, region, sec):
        sec_name = sec.name()
        return any((s._region == region and s._sec.name() == sec_name) for s in self._secs)

    def _region_section(self, region, sec):
        """return the Section1D (or whatever) associated with the region and section"""
        sec_name = sec.name()
        for s in self._secs:
            if s._region == region and s._sec.name() == sec_name:
                return s
        else:
            raise RxDException('requested section not in species')

    def _assign_parents(self):
        root_id = 0
        missing = {}
        self._root_children = []
        for sec in self._secs:
            root_id = sec._assign_parents(root_id, missing, self._root_children)
        self._num_roots = root_id
        # TODO: this probably doesn't do the right thing if the morphology
        #       is changed after creation
        # adjust offsets to account for roots
        if not self._has_adjusted_offsets:
            node._allocate(self._num_roots)
            for sec in self._secs:
                sec._offset += root_id
            self._has_adjusted_offsets = True
    
    
    def _finitialize(self):
        if self.initial is not None:
            if callable(self.initial):
                for node in self.nodes:
                    node.concentration = self.initial(node)
            else:
                for node in self.nodes:
                    node.concentration = self.initial
            self._transfer_to_legacy()            
        else:
            self._import_concentration()
    
    def _transfer_to_legacy(self):
        """Transfer concentrations to the standard NEURON grid"""
        if self._name is None: return
        
        # 1D part
        for sec in self._secs: sec._transfer_to_legacy()
        
        # 3D part
        nodes = self._nodes
        if nodes:
            assert(len(self._regions) == 1)
            r = self._regions[0]
            if r._nrn_region is None: return
            
            # TODO: set volume based on surface nodes or all nodes?
            #       the problem with surface nodes is that surface to volume ratio of these varies greatly
            #
            # TODO: based on tests with real world problems, seems like should use dx ** 3 rather than .volume
            for seg, ptr in zip(self._seg_order, self._concentration_ptrs):
                # concentration = total mass / volume
                ptr[0] = sum(nodes[node].concentration * nodes[node].volume for node in r._nodes_by_seg[seg]) / sum(nodes[node].volume for node in r._nodes_by_seg[seg])
    
    def _import_concentration(self, init=True):
        """Read concentrations from the standard NEURON grid"""
        if self._name is None: return
        
        # start with the 1D stuff
        for sec in self._secs: sec._import_concentration(init)

        # now the 3D stuff
        nodes = self._nodes
        if nodes:
            assert(len(self._regions) == 1)
            r = self._regions[0]
            if r._nrn_region is None: return
            # TODO: replace this with a pointer vec for speed
            for seg, ptr in zip(self._seg_order, self._concentration_ptrs):
                value = ptr[0]
                for node in r._nodes_by_seg[seg]:
                    nodes[node].concentration = value
    
    @property
    def nodes(self):
        """A NodeList of all the nodes corresponding to the species.
        
        This can then be further restricted using the callable property of NodeList objects."""
        initializer._do_init()
        
        # The first part here is for the 1D -- which doesn't keep live node objects -- the second part is for 3D
        return nodelist.NodeList(list(itertools.chain.from_iterable([s.nodes for s in self._secs])) + self._nodes)


    @property
    def name(self):
        """Get or set the name of the Species.

        This is used only for syncing with the non-reaction-diffusion parts of NEURON.
        
        .. note:: Setting only supported in NEURON 7.4+, and then only before the reaction-diffusion model is instantiated.
        """
        return self._name
    
    @name.setter
    def name(self, value):
        if hasattr(self, '_allow_setting'):
            self._name = value
        else:
            raise RxDException('Cannot set name now; model already instantiated')


    def __repr__(self):
        return 'Species(regions=%r, d=%r, name=%r, charge=%r, initial=%r)' % (self._regions, self._d, self._name, self._charge, self.initial)
    
    def __str__(self):
        if self._name is None:
            return self.__repr__()
        return str(self._name)
    

