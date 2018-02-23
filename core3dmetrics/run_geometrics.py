#
# Run all CORE3D metrics and report results.
#

import os
import sys
import shutil
import gdalconst
import numpy as np
import argparse
import json


try:
    import core3dmetrics.geometrics as geo
except:
    import geometrics as geo


# PRIMARY FUNCTION: RUN_GEOMETRICS
def run_geometrics(configfile,refpath=None,testpath=None,outputpath=None,align=True):

    # check inputs
    if not os.path.isfile(configfile):
        raise IOError("Configuration file does not exist")

    if outputpath is not None and not os.path.isdir(outputpath):
        raise IOError('"outputpath" not a valid folder <{}>'.format(outputpath))

    # parse configuration
    configpath = os.path.dirname(configfile)

    config = geo.parse_config(configfile,
        refpath=(refpath or configpath), 
        testpath=(testpath or configpath))

    # Get test model information from configuration file.
    testDSMFilename = config['INPUT.TEST']['DSMFilename']
    testDTMFilename = config['INPUT.TEST'].get('DTMFilename',None)
    testCLSFilename = config['INPUT.TEST']['CLSFilename']
    testMTLFilename = config['INPUT.TEST'].get('MTLFilename',None)

    # Get reference model information from configuration file.
    refDSMFilename = config['INPUT.REF']['DSMFilename']
    refDTMFilename = config['INPUT.REF']['DTMFilename']
    refCLSFilename = config['INPUT.REF']['CLSFilename']
    refNDXFilename = config['INPUT.REF']['NDXFilename']
    refMTLFilename = config['INPUT.REF']['MTLFilename']

    # Get material label names and list of material labels to ignore in evaluation.
    materialNames = config['MATERIALS.REF']['MaterialNames']
    materialIndicesToIgnore = config['MATERIALS.REF']['MaterialIndicesToIgnore']
    
    # Get plot settings from configuration file
    PLOTS_SHOW   = config['PLOTS']['ShowPlots']
    PLOTS_SAVE   = config['PLOTS']['SavePlots']
    PLOTS_ENABLE = PLOTS_SHOW or PLOTS_SAVE

    # default output path
    if outputpath is None:
        outputpath = os.path.dirname(testDSMFilename)

    # Configure plotting
    basename = os.path.basename(testDSMFilename)
    if PLOTS_ENABLE:
        plot = geo.plot(saveDir=outputpath, autoSave=PLOTS_SAVE, savePrefix=basename+'_', badColor='black',showPlots=PLOTS_SHOW, dpi=900)
    else:
        plot = None
        
    # copy testDSM to the output path
    # this is a workaround for the "align3d" function with currently always
    # saves new files to the same path as the testDSM
    src = testDSMFilename
    dst = os.path.join(outputpath,os.path.basename(src))
    if not os.path.isfile(dst): shutil.copyfile(src,dst)
    testDSMFilename_copy = dst

    # Register test model to ground truth reference model.
    if not align:
        print('\nSKIPPING REGISTRATION')
        xyzOffset = (0.0,0.0,0.0)
    else:
        print('\n=====REGISTRATION====='); sys.stdout.flush()
        try:
            align3d_path = config['REGEXEPATH']['Align3DPath']
        except:
            align3d_path = None
        xyzOffset = geo.align3d(refDSMFilename, testDSMFilename_copy, exec_path=align3d_path)

    # Explicitly assign an new no data value to warped images to track filled pixels
    noDataValue = -9999
    
    # Read reference model files.
    print("")
    print("Reading reference model files...")
    refCLS, tform = geo.imageLoad(refCLSFilename)
    refDSM = geo.imageWarp(refDSMFilename, refCLSFilename, noDataValue=noDataValue)
    refDTM = geo.imageWarp(refDTMFilename, refCLSFilename, noDataValue=noDataValue)
    refNDX = geo.imageWarp(refNDXFilename, refCLSFilename, interp_method=gdalconst.GRA_NearestNeighbour).astype(np.uint16)
    refMTL = geo.imageWarp(refMTLFilename, refCLSFilename, interp_method=gdalconst.GRA_NearestNeighbour).astype(np.uint8)

    # Read test model files and apply XYZ offsets.
    print("Reading test model files...")
    print("")
    testCLS = geo.imageWarp(testCLSFilename, refCLSFilename, xyzOffset, gdalconst.GRA_NearestNeighbour)
    testDSM = geo.imageWarp(testDSMFilename, refCLSFilename, xyzOffset, noDataValue=noDataValue)
    testDSM = testDSM + xyzOffset[2]

    if testDTMFilename:
        testDTM = geo.imageWarp(testDTMFilename, refCLSFilename, xyzOffset, noDataValue=noDataValue)
    else:
        print('NO TEST DTM: defaults to reference DTM')
        testDTM = refDTM

    if testMTLFilename:
        testMTL = geo.imageWarp(testMTLFilename, refCLSFilename, xyzOffset, gdalconst.GRA_NearestNeighbour).astype(np.uint8)

    # Apply registration offset, only to valid data to allow better tracking of bad data
    testValidData = (testDSM != noDataValue) & (testDSM != noDataValue)
    testDSM[testValidData] = testDSM[testValidData] + xyzOffset[2]
    if testDTMFilename:
        testDTM[testValidData] = testDTM[testValidData] + xyzOffset[2]

    # object masks based on CLSMatchValue(s)
    refMask = np.zeros_like(refCLS, np.bool)
    # For CLS value 256, evaluate against all non-zero pixels
    # CLS values should range from 0 to 255 per ASPRS
    # (American Society for Photogrammetry and Remote Sensing)
    # LiDAR point cloud classification LAS standard
    if config['INPUT.REF']['CLSMatchValue'] == [256]:
        refMask[refCLS != 0] = True
    else:
        for v in config['INPUT.REF']['CLSMatchValue']:
            refMask[refCLS == v] = True

    testMask = np.zeros_like(testCLS, np.bool)
    if config['INPUT.TEST']['CLSMatchValue'] == [256]:
        testMask[testCLS != 0] = True
    else:
        for v in config['INPUT.TEST']['CLSMatchValue']:
            testMask[testCLS == v] = True

    # Create mask for ignoring points labeled NoData in reference files.
    refDSM_NoDataValue = geo.getNoDataValue(refDSMFilename)
    refDTM_NoDataValue = geo.getNoDataValue(refDTMFilename)
    refCLS_NoDataValue = geo.getNoDataValue(refCLSFilename)
    ignoreMask = np.zeros_like(refCLS, np.bool)

    if refDSM_NoDataValue is not None:
        ignoreMask[refDSM == refDSM_NoDataValue] = True
    if refDTM_NoDataValue is not None:
        ignoreMask[refDTM == refDTM_NoDataValue] = True
    if refCLS_NoDataValue is not None:
        ignoreMask[refCLS == refCLS_NoDataValue] = True

    # If quantizing to voxels, then match vertical spacing to horizontal spacing.
    QUANTIZE = config['OPTIONS']['QuantizeHeight']
    if QUANTIZE:
        unitHgt = geo.getUnitHeight(tform)
        refDSM = np.round(refDSM / unitHgt) * unitHgt
        refDTM = np.round(refDTM / unitHgt) * unitHgt
        testDSM = np.round(testDSM / unitHgt) * unitHgt
        testDTM = np.round(testDTM / unitHgt) * unitHgt
        noDataValue = np.round(noDataValue / unitHgt) * unitHgt
       
    if PLOTS_ENABLE:
        # Reference models can bad voids, so ignore bad data on display
        plot.make(refDSM, 'Reference DSM', 111, colorbar=True, saveName="input_refDSM", badValue=noDataValue)
        plot.make(refDTM, 'Reference DTM', 112, colorbar=True, saveName="input_refDTM", badValue=noDataValue)
        plot.make(testCLS, 'Reference Classification', 113,  colorbar=True, saveName="input_refClass")
        plot.make(testMask.astype(np.int), 'Reference Evaluation Mask', 114, colorbar=True, saveName="input_refMask")

        # Test models shouldn't have any bad data,
        # so display the bad values to highlight them,
        # unlike with the refSDM/refDTM
        plot.make(testDSM, 'Test DSM', 151, colorbar=True, saveName="input_testDSM")
        plot.make(testDTM, 'Test DTM', 152, colorbar=True, saveName="input_testDTM")
        plot.make(testCLS, 'Test Classification', 153, colorbar=True, saveName="input_testClass")
        plot.make(testMask.astype(np.int), 'Test Evaluation Mask', 154, colorbar=True, saveName="input_testMask")

        plot.make(ignoreMask, 'Ignore Mask', 181, saveName="input_ignoreMask")


    # Run the threshold geometry metrics and report results.
    metrics = dict()
    metrics['threshold_geometry'] = geo.run_threshold_geometry_metrics(refDSM, refDTM, refMask, testDSM, testDTM, testMask,
                                       tform, ignoreMask, plot=plot)

    metrics['registration_offset'] = xyzOffset
    # Run the terrain model metrics and report results.
    dtm_z_threshold = config['OPTIONS'].get('TerrainZErrorThreshold',1)
    metrics['terrain_accuracy'] = geo.run_terrain_accuracy_metrics(refDSM, refDTM, testDSM, testDTM, refMask, testMask, dtm_z_threshold, geo.getUnitArea(tform), plot=plot)
    metrics['relative_accuracy'] = geo.run_relative_accuracy_metrics(refDSM, testDSM, refMask, testMask, geo.getUnitWidth(tform), plot=plot)
    metrics['offset'] = xyzOffset
    
    fileout = os.path.join(outputpath,os.path.basename(testDSMFilename) + "_metrics.json")
    with open(fileout,'w') as fid:
        json.dump(metrics,fid,indent=2)
    print(json.dumps(metrics,indent=2))

    # Run the threshold material metrics and report results.
    if testMTLFilename:
        geo.run_material_metrics(refNDX, refMTL, testMTL, materialNames, materialIndicesToIgnore)
    else:
        print('WARNING: No test MTL file, skipping material metrics')

    #  If displaying figures, wait for user before existing
    if PLOTS_SHOW:
            input("Press Enter to continue...")

# command line function
def main(args=None):
    if args is None:
        args = sys.argv[1:]
        
    # parse inputs
    parser = argparse.ArgumentParser(description='core3dmetrics entry point', prog='core3dmetrics')
    parser.add_argument('-c', '--config', dest='config',
                            help='Configuration file', required=True, metavar='')
    parser.add_argument('-r', '--reference', dest='refpath', 
                            help='Reference data folder', required=False, metavar='')
    parser.add_argument('-t', '--test', dest='testpath', 
                            help='Test data folder', required=False, metavar='')
    parser.add_argument('-o', '--output', dest='outputpath', 
                            help='Output folder', required=False, metavar='')
    
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument('--align', dest='align', action='store_true')
    group.add_argument('--no-align', dest='align', action='store_false')
    group.set_defaults(align=True)

    args = parser.parse_args()
    
    # gather optional arguments
    kwargs = {}
    if args.refpath: kwargs['refpath'] = args.refpath
    if args.testpath: kwargs['testpath'] = args.testpath
    if args.outputpath: kwargs['outputpath'] = args.outputpath
    
    # run process
    run_geometrics(configfile=args.config,align=args.align,**kwargs)

if __name__ == "__main__":
    main()
