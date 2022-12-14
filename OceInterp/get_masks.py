import numpy as np
import xarray as xr 
import copy
import warnings
from OceInterp.topology import topology
from OceInterp.smart_read import smart_read
from OceInterp.RuntimeConf import rcParam

def mask_u_node(maskC,tp):
    '''
    for MITgcm indexing, U is defined on the left of the cell,
    When the C grid is dry, U are either:
    a. dry;
    b. on the interface, where the cell to the left is wet.
    if b is the case, we need to unmask the udata
    '''
        
    maskU = copy.deepcopy(maskC)
    indexes = np.array(np.where(maskC==0)).T
    ### find out which points are masked will make the search faster.
    nind = tp.ind_tend_vec(indexes.T[1:],np.ones_like(indexes.T[0],int)*2)
    nind = np.vstack([indexes.T[0],nind])
    switch = indexes[np.where(maskC[tuple(nind)])]
    maskU[tuple(switch.T)] = 1
    
    return maskU

def mask_v_node(maskC,tp):
    '''
    for MITgcm indexing, V is defined on the "south" side of the cell,
    When the C grid is dry, V are either:
    a. dry;
    b. on the interface, where the cell to the downside is wet.
    if b is the case, we need to unmask the vdata
    '''
    maskV = copy.deepcopy(maskC)
    indexes = np.array(np.where(maskC==0)).T
    ### find out which points are masked will make the search faster.
    nind = tp.ind_tend_vec(indexes.T[1:],np.ones_like(indexes.T[0],int)*1)
    nind = np.vstack([indexes.T[0],nind])
    switch = indexes[np.where(maskC[tuple(nind)])]
    maskV[tuple(switch.T)] = 1
    return maskV


def mask_w_node(maskC,tp = None):
    # this one does not need tp object
    # if you pass something into it by mistake, it will be ignored. 
    '''
    for MITgcm indexing, W is defined on the top of the cell,
    When the C grid is dry, W are either:
    a. dry;
    b. on the interface, where the cell above is wet.
    if b is the case, we need to unmask the wdata
    '''
    temp = np.zeros_like(maskC)
    temp[1:] = maskC[:-1]
    maskW = np.logical_or(temp,maskC).astype(int)
    return maskW
    
def get_masks(od,tp):
    '''
    just put the above functions together.
    '''
    tp = topology(od)
    keys = od._ds.keys()
    if 'maskC' not in keys:
        warnings.warn('no maskC in the dataset, assuming nothing is masked.')
        print('no maskC in the dataset, assuming nothing is masked.')
        # od._ds.C_GRID_VARIABLE.to_masked_array().mask
        maskC = np.ones_like(od._ds.XC+od._ds.Z)
        # it is inappropriate to fill in the dataset, 
        # expecially given that there is no performance boost.
        return maskC,maskC,maskC,maskC
    maskC = np.array(od._ds['maskC'])
    if 'maskU' not in keys:
        print('creating maskU,this is going to be very slow!')
        maskU = mask_u_node(maskC,tp)
        od._ds['maskU'] = od._ds['Z']+od._ds['XG']
        od._ds['maskU'].values = maskU
    else:
        maskU = np.array(od._ds['maskU'])
    if 'maskV' not in keys:
        print('creating maskV,this is going to be very slow!')
        maskV = mask_v_node(maskC,tp)
        od._ds['maskV'] = od._ds['Z']+od._ds['YG']
        od._ds['maskV'].values = maskV
    else:
        maskV = np.array(od._ds['maskV'])
    if 'maskWvel' not in keys:
        # there is a maskW with W meaning West in ECCO
        print('creating maskW,this is going to be somewhat slow')
        maskW = mask_w_node(maskC)
        od._ds['maskWvel'] = od._ds['Z']+od._ds['YC']
        od._ds['maskWvel'].values = maskW
        # this dimension is actually not quite right
        # TODO: create the correct dimension
        # done
    else:
        maskW = np.array(od._ds['maskWvel'])
    return maskC,maskU,maskV,maskW

def get_masked(od,ind,gridtype = 'C'):
    if gridtype not in ['C','U','V','Wvel']:
        raise NotImplementedError('gridtype for mask not supported')
    keys = od._ds.keys()
    if 'maskC' not in keys:
        warnings.warn('no maskC in the dataset, assuming nothing is masked.')
#         print('no maskC in the dataset, assuming nothing is masked.')
        # od._ds.C_GRID_VARIABLE.to_masked_array().mask
        return np.ones_like(ind[0])
    elif gridtype == 'C':
        return smart_read(od._ds.maskC,ind)
    
    name = 'mask'+gridtype
    tp = topology(od)
    maskC = np.array(od._ds['maskC'])
    func_dic = {'U':mask_u_node,'V':mask_v_node,'Wvel':mask_w_node}
    rename_dic = {
        'U':lambda x: x if x!='X' else 'Xp1',
        'V':lambda x: x if x!='Y' else 'Xp1',
        'Wvel':lambda x: x if x!='Z' else 'Zl',
    }
    if name not in keys:
        if rcParam['debug_level'] in ['high','very_high']:
            print(f'creating {name}, this is going to be slow!')
        small_mask = func_dic[gridtype](maskC,tp)
        dims = tuple(map(
                                           rename_dic[gridtype],
                                           od._ds.maskC.dims
                                       ))
        sizes = tuple([len(od._ds[dim]) for dim in dims])
#         print(sizes)
        mask = np.zeros(sizes)
        #indexing sensitive
        old_size = small_mask.shape
        slices = tuple([slice(0,i) for i in old_size])
#         print(ind_str)
        mask[slices] = small_mask
        od._ds[name] = xr.DataArray(mask,
                                    dims = dims
                                   )
        return mask[ind]
    else:
        return smart_read(od._ds[name],ind)