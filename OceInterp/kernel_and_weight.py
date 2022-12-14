import numpy as np
from numba import njit
import matplotlib.pyplot as plt
import copy

from OceInterp.utils import get_combination
from OceInterp.topology import topology

# default kernel for interpolation.
default_kernel = np.array([
    [0,0],
    [0,1],
    [0,2],
    [0,-1],
    [0,-2],
    [-1,0],
    [-2,0],
    [1,0],
    [2,0]
])
default_russian_doll = [
    [0,1,2,3,4,5,6,7,8],
    [0,1,2,3,5,7,8],
    [0,1,3,5,7],
    [0]
]
default_kernels = [np.array([default_kernel[i] for i in doll]) for doll in default_russian_doll]

# It just tell you what the kernels look like
def show_kernels(kernels = default_kernels):
    for i,k in enumerate(kernels):
        x,y = k.T
        plt.plot(x+0.1*i,y+0.1*i,'+')
    
def translate_to_tendency(k):
    '''
    A kernel looks like 
    np.array([
    [x1,y1],
    [x2,y2],....
    ])
    where [xn,yn] represent a coordinate relative to [0,0]
    which is just the nearest neighbor.
    this function return how you could move from [0,0] to k = [x,y]
    If you need to go to [0,2], you need to move up twice.
    it will return [0,0] or more explicitly ['up','up']
    [0,0] will produce a empty array.
    '''
    tend = []
    x,y = k 
    if y>0:
        for j in range(y):
            tend.append(0)#up
    else:
        for j in range(-y):
            tend.append(1)#down
    if x<0:
        for j in range(-x):
            tend.append(2)#left
    else:
        for j in range(x):
            tend.append(3)#right
    return tend

def fatten_ind_h(faces,iys,ixs,tp,kernel=default_kernel):
    '''
    faces,iys,ixs is now 1d arrays of size n. 
    We are applying a kernel of size m.
    This is going to return a n * m array of indexes.
    each row represen all the node needed for interpolation of a single point.
    "h" represent we are only doing it on the horizontal plane
    '''
    kernel_tends =  [translate_to_tendency(k) for k in kernel]
    m = len(kernel_tends)
    n = len(iys)
    
    # the arrays we are going to return 
    if faces is not None:
        n_faces = np.zeros((n,m))
        n_faces.T[:] = faces
    n_iys = np.zeros((n,m))
    n_ixs = np.zeros((n,m))
    
    # first try to fatten it naively(fast and vectorized)
    for i,node in enumerate(kernel):
        x_disp,y_disp = node
        n_iys[:,i] = iys+y_disp
        n_ixs[:,i] = ixs+x_disp
    if faces is not None:
        illegal = tp.check_illegal((n_faces,n_iys,n_ixs))
    else:
        illegal = tp.check_illegal((n_iys,n_ixs))
        
    redo = np.array(np.where(illegal)).T
    for num,loc in enumerate(redo):
        j,i = loc
        if faces is not None:
            ind = (faces[j],iys[j],ixs[j])
        else:
            ind = (iys[j],ixs[j])
        # everyone start from the [0,0] node
        moves = kernel_tends[i]
        # moves is a list of operations to get to a single point
        #[2,2] means move to the left and then move to the left again.
        n_ind = tp.ind_moves(ind,moves)
        if faces is not None:
            n_faces[j,i],n_iys[j,i],n_ixs[j,i] = n_ind
        else:
            n_iys[j,i],n_ixs[j,i] = n_ind
    if faces is not None:
        return n_faces.astype('int'),n_iys.astype('int'),n_ixs.astype('int')
    else:
        return None,n_iys.astype('int'),n_ixs.astype('int')

def fatten_ind_3d(iz,faces,iy,ix,tp,kernel=default_kernel):
    '''
    fatten the kernel some more in the vertical direcion,
    (1-rz)*this_layer+rz*that_layer
    essentially, there are only two points in the vertical kernel.
    more generally it should be kronecker product, I find it kind of 
    unnecessary.
    '''
    ffaces,fiy,fix = fatten_ind_h(faces,iy,ix,tp,kernel)
    n,m = fiy.shape
    fiz = np.zeros_like(fiy)
    fiz = np.concatenate((fiz,fiz),axis = 1)
    for i in range(len(fiz)):
        fiz[i,:m] = iz[i]
        if iz[i]!=0:
            fiz[i,m:] = iz[i]-1
        # the commented lines below are not necessary,
        # but it make it easier to explain what we are doing.
        # if when we are considering the top level,
        # we just do a 2D interpolation.
        # top_layer = (1-rz)*top_layer+rz*top_layer
        # it will be more obvious after you read the function of weight
#         else:
#             fiz[i,m:] = iz[i]
    if faces is None:
        ffaces = None
    else:
        ffaces = np.concatenate((ffaces,ffaces),axis = 1)
    fiy = np.concatenate((fiy,fiy),axis = 1)
    fix = np.concatenate((fix,fix),axis = 1)
    return fiz,ffaces,fiy,fix

def fatten_linear_dim(iz,ind,maximum = None,minimum = None,kernel_type = 'linear'):
    '''
    this function linearly fattened the index in t or z dimension
    '''
    if maximum and minimum:
        raise Exception('either interpolate the node with'
                        'larger index (provide maximum) or lower index(provide )')
    ori_shape = ind[-1].shape
    n_ind = []
    if kernel_type in ['linear','dz']:
        new_shape = list(ori_shape)
        new_shape.append(2)
        added_dim = np.zeros(new_shape[::-1])
        added_dim[0] = iz
        if minimum is not None:
            added_dim[1] = np.maximum(minimum,iz-1)
        elif maximum is not None:
            added_dim[1] = np.minimum(maximum,iz+1)
        else:
            added_dim[1] = iz-1
        n_ind.append(added_dim.T.astype(int))
        
        for idim in ind:
            if idim is not None:
                n_ind.append(np.stack((idim,idim),axis = -1))
            else:
                n_ind.append(None)

    elif kernel_type == 'nearest':
        new_shape = list(ori_shape)
        new_shape.append(1)
        added_dim = np.zeros(new_shape)
        added_dim.T[:] = iz
        n_ind.append(added_dim.astype(int))
        for idim in ind:
            if idim is not None:
                n_ind.append(idim.reshape(new_shape))
            else:
                n_ind.append(None)
    else:
        raise Exception('kernel_type not recognized. should be either linear, dz, or nearest')
    return tuple(n_ind)
    
def fatten_ind_4d(it,iz,face,iy,ix,tp,
               hkernel=default_kernel,
               zkernel='linear',
               tkernel='linear',
              ):
    # perform horizontal fattening 
    hface,hiy,hix = fatten_ind_h(face,iy,ix,tp,hkernel)
    
    # perform vertical
    n,m = hiy.shape
    if zkernel in ['linear','dz']:
        vhiy = np.stack((hiy,hiy),axis = -1)
        vhix = np.stack((hix,hix),axis = -1)
        if face is not None:
            vhface = np.stack((hface,hface),axis = -1)
        vhiz = np.zeros((2,m,n))
        vhiz[0] = iz
        vhiz[1] = (abs(iz-1)+(iz-1))/2 #relu function
        vhiz = vhiz.T
    elif zkernel == 'nearest':
        vhiy = hiy.reshape((n,m,1))
        vhix = hix.reshape((n,m,1))
        vhiz = np.zeros((n,m,1))
        vhiz.T[:] = iz
    else:
        raise Exception('zkernel not recognized. should be either linear, dz, or nearest')

    # perform temperal
    n,m,p = vhiy.shape
    if tkernel in ['linear','dt']:
        tvhiy = np.stack((vhiy,vhiy),axis = -1)
        tvhix = np.stack((vhix,vhix),axis = -1)
        tvhiz = np.stack((vhiz,vhiz),axis = -1)
        if face is not None:
            tvhface = np.stack((vhface,vhface),axis = -1)
        tvhit = np.zeros((2,p,m,n))
        tvhit[0] = it
        tvhit[1] = np.minimum(tp.itmax,it+1)
        tvhit = tvhit.T
    elif tkernel == 'nearest':
        tvhiy = vhiy.reshape(n,m,p,1)
        tvhix = vhix.reshape(n,m,p,1)
        tvhiz = vhiz.reshape(n,m,p,1)
        tvhit = np.zeros((n,m,p,1))
        tvhit.T[:] = it
    else:
        raise Exception('tkernel not recognized. should be either linear, dt, or nearest')
        
    if face is None:
        tvhface = None
    return tvhit.astype(int),tvhiz.astype(int),tvhface.astype(int),tvhiy.astype(int),tvhix.astype(int)

def kernel_weight_x(kernel,ktype = 'interp',order = 0):
    '''
    return the function that calculate the weight
    given a cross-shaped (that's where x is coming from) kernel.
    ktype can be choosen from "interp","x","y"
    order is the order of derivatives.
    
    Those functions are a bit complicated, so it takes time to compile,
    after that, they are great. 
    '''
    xs = np.array(list(set(kernel.T[0]))).astype(float)
    ys = np.array(list(set(kernel.T[1]))).astype(float)
    
    # if you the kernel is a line rather than a cross
    if len(xs) == 1:
        ktype = 'y'
    elif len(ys)==1:
        ktype = 'x'
    
    """
    If you don't want to know what is going on under the hood.
    it's totally fine.
    
    all of the following is a bit hard to understand.
    The k th (k>=0) derivative of the lagrangian polynomial is 
          \Sigma_{i\neq j} \Pi_{i<m-1-k} (x-x_i)
    w_j= ----------------------------------------
          \Pi_{i\neq j} (x_j - x_i)
    
    for example: if the points are [-1,0,1] for point 0
    k = 0: w = (x-1)(x+1)/(0-1)(0+1)
    k = 1: w = [(x+1)+(x-1)]/(0-1)(0+1)
    
    for a cross shape kernel:
    f(rx,ry) = f_x(rx) + f_y(ry) - f(0,0)
    
    The following equation is just that.
    """
    
    x_poly = []
    y_poly = []
    if ktype == 'interp':
        for ax in xs:
            x_poly.append(get_combination([i for i in xs if i!=ax],len(xs)-1))
        for ay in ys:
            y_poly.append(get_combination([i for i in ys if i!=ay],len(ys)-1))
    if ktype == 'x':
        for ax in xs:
            x_poly.append(
                get_combination([i for i in xs if i!=ax],len(xs)-1-order))
        y_poly=[[[]]]
    if ktype == 'y':
        x_poly = [[[]]]
        for ay in ys:
            y_poly.append(
                get_combination([i for i in ys if i!=ay],len(ys)-1-order))
    x_poly = np.array(x_poly).astype(float)
    y_poly = np.array(y_poly).astype(float)
    @njit
    def the_interp_func(rx,ry):
        nonlocal kernel,xs,ys,x_poly,y_poly
        n = len(rx)
        m = len(kernel)
        weight = np.ones((n,m))*0.0
        for i,(x,y) in enumerate(kernel):
            if x!=0:
                ix = np.where(xs==x)[0][0]
                poly = x_poly[ix]
                for term in poly:
                    another = np.ones(n)
                    for other in term:
                        another*=(rx-other)
                    weight[:,i]+=another
                    for other in xs:
                        if other!=x:
                            weight[:,i]/=(x-other)
            if y!=0:
                iy = np.where(ys==y)[0][0]
                poly = y_poly[iy]
                for term in poly:
                    another = np.ones(n)*1.0
                    for other in term:
                        another*=(ry-other)
                    weight[:,i]+=another
                    for other in ys:
                        if other!=y:
                            weight[:,i]/=(y-other)
            elif x**2+y**2==0:
                xthing = np.zeros(n)*0.0
                ix = np.where(xs==0)[0][0]
                poly = x_poly[ix]
                for term in poly:
                    another = np.ones(n)*1.0
                    for other in term:
                        another*=(rx-other)
                    xthing+=another
                    for other in xs:
                        if other!=x:
                            xthing/=(x-other)
                
                ything = np.zeros(n)*0.0
                iy = np.where(ys==y)[0][0]
                poly = y_poly[iy]
                for term in poly:
                    another = np.ones(n)
                    for other in term:
                        another*=(ry-other)
                    ything+=another
                    for other in ys:
                        if other!=y:
                            ything/=(y-other)
                weight[:,i]=xthing+ything-1
        return weight
    @njit
    def the_x_func(rx,ry):
        nonlocal kernel,xs,ys,x_poly,order
        n = len(rx)
        m = len(kernel)
        weight = np.ones((n,m))*0.0
        for i,(x,y) in enumerate(kernel):
            if y==0:
                ix = np.where(xs==x)[0][0]
                poly = x_poly[ix]
                for term in poly:
                    another = np.ones(n)*1.0
                    for other in term:
                        another*=(rx-other)
                    
                    weight[:,i]+=another
                for other in xs:
                    if other!=x:
                        weight[:,i]/=(x-other)
        return weight
    @njit
    def the_x_maxorder_func(rx,ry):
        nonlocal kernel,xs,ys,order
        n = len(rx)
        m = len(kernel)
        common = 1
        for i in range(1,order):
            common*=i
        weight = np.ones((n,m))*float(common)
        for i,(x,y) in enumerate(kernel):
            if y==0:
                for other in xs:
                    if other!=x:
                        weight[:,i]/=(x-other)
            else:
                weight[:,i] = 0.0
        return weight
    @njit
    def the_y_func(rx,ry):
        nonlocal kernel,xs,ys,y_poly,order
        n = len(rx)
        m = len(kernel)
        weight = np.ones((n,m))*0.0
        for i,(x,y) in enumerate(kernel):
            if x==0:
                iy = np.where(ys==y)[0][0]
                poly = y_poly[iy]
                for term in poly:
                    another = np.ones(n)*1.0
                    for other in term:
                        another*=(ry-other)
                    
                    weight[:,i]+=another
                for other in ys:
                    if other!=y:
                        weight[:,i]/=(y-other)
        return weight
    @njit
    def the_y_maxorder_func(rx,ry):
        nonlocal kernel,xs,ys,order
        n = len(rx)
        m = len(kernel)
        common = 1
        for i in range(1,order):
            common*=i
        weight = np.ones((n,m))*float(common)
        for i,(x,y) in enumerate(kernel):
            if x==0:
                for other in ys:
                    if other!=y:
                        weight[:,i]/=(y-other)
            else:
                weight[:,i] = 0.0
        return weight
    if ktype == 'interp':
        return the_interp_func
    if ktype =='x':
        max_order = len(xs)-1
        if order<max_order:
            return the_x_func
        elif order == max_order:
            return the_x_maxorder_func
        else:
            raise Exception('Kernel is too small for this derivative')
    if ktype =='y':
        max_order = len(ys)-1
        if order<max_order:
            return the_y_func
        elif order == max_order:
            return the_y_maxorder_func
        else:
            raise Exception('Kernel is too small for this derivative')
# we can define the default interpolation functions here, 
# so if we are using it over and over, we don't have to compile it.
# and it really takes a lot of time to compile. 

def kernel_weight_s(kernel,xorder = 0,yorder = 0):
    xs = np.array(list(set(kernel.T[0]))).astype(float)
    ys = np.array(list(set(kernel.T[1]))).astype(float)
    xmaxorder = False
    ymaxorder = False
    if xorder<len(xs)-1:
        pass
    elif xorder == len(xs)-1:
        xmaxorder = True
    else:
        raise Exception('Kernel is too small for this derivative')
        
    if yorder<len(ys)-1:
        pass
    elif yorder == len(ys)-1:
        ymaxorder = True
    else:
        raise Exception('Kernel is too small for this derivative')

    x_poly = []
    y_poly = []
    for ax in xs:
        x_poly.append(
            get_combination([i for i in xs if i!=ax],len(xs)-1-xorder))
    for ay in ys:
        y_poly.append(
            get_combination([i for i in ys if i!=ay],len(ys)-1-yorder))
    x_poly = np.array(x_poly).astype(float)
    y_poly = np.array(y_poly).astype(float)
    @njit
    def the_square_func(rx,ry):
        nonlocal kernel,xs,ys,y_poly,x_poly,xorder,yorder
        n = len(rx)
        mx = len(xs)
        my = len(ys)
        m = len(kernel)
        yweight = np.ones((n,my))
        xweight = np.ones((n,mx))
        weight = np.ones((n,m))*0.0

        if ymaxorder:
            common = 1
            for i in range(1,yorder):
                common*=i
            yweight *=float(common)
        else:
            yweight *= 0.0
        for i,y in enumerate(ys):
            if not ymaxorder:
                iy = np.where(ys==y)[0][0]
                poly = y_poly[iy]
                for term in poly:
                    another = np.ones(n)*1.0
                    for other in term:
                        another*=(ry-other)

                    yweight[:,i]+=another
            for other in ys:
                if other!=y:
                    yweight[:,i]/=(y-other)


        if xmaxorder:
            common = 1
            for i in range(1,xorder):
                common*=i
            xweight *=float(common)
        else:
            xweight *= 0.0
        for i,x in enumerate(xs):
            if not xmaxorder:
                ix = np.where(xs==x)[0][0]
                poly = x_poly[ix]
                for term in poly:
                    another = np.ones(n)*1.0
                    for other in term:
                        another*=(rx-other)

                    xweight[:,i]+=another
            for other in xs:
                if other!=x:
                    xweight[:,i]/=(x-other)

        for i,(x,y) in enumerate(kernel):
            iy = np.where(ys==y)[0][0]
            ix = np.where(xs==x)[0][0]
            weight[:,i] = yweight[:,iy]*xweight[:,ix]

        return weight
    return the_square_func

def kernel_weight(kernel,ktype = 'interp',order = 0):
    mx = len(set(kernel[:,0]))
    my = len(set(kernel[:,1]))
    if len(kernel) == mx+my-1:
        if 'd' in ktype:
            ktype = ktype[1:]
        return kernel_weight_x(kernel,ktype = ktype,order = order)
    elif len(kernel) == mx*my:# mx*my == mx+my-1 only when mx==1 or my ==1
        if ktype == 'interp':
            return kernel_weight_s(kernel,xorder = 0,yorder = 0)
        elif ktype == 'dx':
            return kernel_weight_s(kernel,xorder = order,yorder = 0)
        elif ktype == 'dy':
            return kernel_weight_s(kernel,xorder = 0,yorder = order)

default_interp_funcs = [kernel_weight_x(a_kernel) for a_kernel in default_kernels]

def find_which_points_for_each_kernel(masked,russian_doll = default_russian_doll):
    '''
    masked is going to be a n*m array,
    where n is the number of points of interest.
    m is the size of the largest kernel.
    
    russian_doll defines the shape of smaller kernels.
    say
    russian_doll = [
    [0,1,2,3,4],
    [0,1],
    [0]
    ]
    it means that the largest kernel have all 5 nodes
    the second kernel only contain the first and second node,
    and the last one only have the nearest neighbor. 
    
    if a row of matrix looks like [1,1,1,1,1],
    the index of the row will be in the first element(list) of the return variable.
    
    if a row of matrix looks like [1,1,1,1,0],
    although it fits both 2nd and 3rd kernel, 2nd has priority, so the index will
    be in the 2nd element of the return pk.
    
    if a row looks like [0,0,0,0,0],
    none of the kernel can fit it, so the index will not be in the return
    '''
    already_wet = []
    for i,doll in enumerate(russian_doll):
        wet_1d = masked[:,np.array(doll)].all(axis = 1)
        already_wet.append(np.where(wet_1d==True)[0])
    point_for_each_kernel = [list(already_wet[0])]
    for i in range(1,len(russian_doll)):
        point_for_each_kernel.append(
            list(np.setdiff1d(already_wet[i],already_wet[i-1]))
        )
    return point_for_each_kernel

def get_weight_cascade(rx,ry,pk,
                       kernel_large = default_kernel,
                       russian_doll = default_russian_doll,
                       funcs = default_interp_funcs):
    weight = np.zeros((len(rx),len(kernel_large)))
    weight[:,0] = np.nan
    '''
    apply the corresponding functions that was figured out in 
    find_which_points_for_each_kernel
    '''
    for i in range(len(pk)):
        if len(pk[i]) == 0:
            continue
        sub_rx = rx[pk[i]]
        sub_ry = ry[pk[i]]
    #     slim_weight = interp_func[i](sub_rx,sub_ry)
        sub_weight = np.zeros((len(pk[i]),len(kernel_large)))
        sub_weight[:,np.array(russian_doll[i])] = funcs[i](sub_rx,sub_ry)
        weight[pk[i]] = sub_weight
    return weight

def find_which_points_for_2layer_kernel(masked,russian_doll = default_russian_doll):
    # extend the find_which_points_for_each_kernel to the z dimension
    n,m = masked.shape
    m = m//2
    pk1 = find_which_points_for_each_kernel(masked[:,:m],russian_doll)
    pk2 = find_which_points_for_each_kernel(masked[:,m:],russian_doll)
    return pk1,pk2

def get_weight_2layer(rx,ry,rz,pk1,pk2,bc = 'no_flux',
                      kernel_large = default_kernel,
                       russian_doll = default_russian_doll,
                       funcs = default_interp_funcs):
    n = len(rx)
    m = len(kernel_large)
    weight = np.zeros((n,2*m))
    # here the weight is multiplied by rz, which is just the weight associated with z location
    # essentially a 2-point interpolation
    weight[:,:m] = (get_weight_cascade(rx,ry,pk1,kernel_large,russian_doll,funcs).T*(1-rz)).T
    weight[:,m:] = (get_weight_cascade(rx,ry,pk2,kernel_large,russian_doll,funcs).T*rz).T
    if bc == 'no_flux':
        # for salt the natural bottom bc is no_flux,
        # between the lowest wet node and the dry node right under it.
        # the gradient shoule be zero, and a nearest neighbor interpolation should be used.
        # rather than returning nan
        for i in range(n):
            if np.isnan(weight[i,m]) and not np.isnan(weight[i,0]):
                weight[i,m] = 0
    return weight

def find_pk_4d(masked,russian_doll = default_russian_doll):
    maskedT = masked.T
    ind_shape = maskedT.shape
    tz = []
    for i in range(ind_shape[0]):
        z = []
        for j in range(ind_shape[1]):
            z.append(find_which_points_for_each_kernel(maskedT[i,j].T,russian_doll))
        tz.append(z)
    return tz

def get_weight_4d(rx,ry,rz,rt,
                  pk4d,
                  hkernel = default_kernel,
                  russian_doll = default_russian_doll,
                  funcs = default_interp_funcs,
                  tkernel = 'linear',#'dt','nearest'
                  zkernel = 'linear',#'dz','nearest'
                  bottom_scheme = 'no flux'# None
                 ):
    nt = len(pk4d)
    nz = len(pk4d[0])
    
    if tkernel == 'linear':
        rp = copy.deepcopy(rt)
        tweight = [(1-rp).reshape((len(rp),1,1)),rp.reshape((len(rp),1,1))]
    elif tkernel == 'dt':
        tweight = [-1,1]
    elif tkernel == 'nearest':
        tweight = [1,0]

    if zkernel == 'linear':
        rp = copy.deepcopy(rz)
        zweight = [(1-rp).reshape((len(rp),1)),rp.reshape((len(rp),1))]
    elif zkernel == 'dz':
        zweight = [-1,1]
    elif zkernel == 'nearest':
        zweight = [1,0]

    weight = np.zeros((len(rx),len(hkernel),nz,nt))
    for jt in range(nt):
        for jz in range(nz):
            weight[:,:,jz,jt] =   get_weight_cascade(rx,ry,
                                                      pk4d[jt][jz],
                                                      kernel_large = hkernel,
                                                      russian_doll = russian_doll,
                                                      funcs = funcs
                                                     )
    for jt in range(nt):
        if (zkernel == 'linear') and (bottom_scheme == 'no flux'):
            # whereever the bottom layer is masked, replace it with a ghost point above it
            secondlayermasked = np.isnan(weight[:,:,0,jt]).any(axis = 1)
            # setting the value at this level zero
            weight[secondlayermasked,:,0,jt] = 0
            shouldbemasked = np.logical_and(secondlayermasked,rz<1/2)
            weight[shouldbemasked,:,1,jt] = 0
            # setting the vertical weight of the above value to 1
            zweight[1][secondlayermasked] = 1
        for jz in range(nz):
            weight[:,:,jz,jt] *= zweight[jz]
        weight[:,:,:,jt]*=tweight[jt]
#         break

    return weight