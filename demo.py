# -*-coding:utf-8-*
__author__ = 'Iacopo'
import renderer
import facial_feature_detector as feature_detection
import camera_calibration as calib
import scipy.io as io
import cv2
import numpy as np
import os
import check_resources as check
import matplotlib.pyplot as plt
import sys
import myutil
import ThreeD_Model
import config

""" 读取 config.ini
"""
# 获取文件当前所在的绝对路径
this_path = os.path.dirname(os.path.abspath(__file__))
# 获取配置文件config.ini对象
opts = config.parse()

""" 读取配置文件中 [render] newRenderedViews 的属性值
    newRenderedViews = yes，使用models3d_new文件夹中的头部模型（清晰度更高、姿态更多）[当前]
                     = false，使用models3d文件夹中的头部模型
"""
## 3D Models we are gonna use to to the rendering {0, -40, -75}
newModels = opts.getboolean('renderer', 'newRenderedViews')
if opts.getboolean('renderer', 'newRenderedViews'):
    pose_models_folder = '/models3d_new/'
    pose_models = ['model3D_aug_-00_00','model3D_aug_-22_00','model3D_aug_-40_00','model3D_aug_-55_00','model3D_aug_-75_00']
else:
    pose_models_folder = '/models3d/'
    pose_models = ['model3D_aug_-00','model3D_aug_-40','model3D_aug_-75',]

""" 如果 [general] resnetON 激活，则设置一些参数以生成最适合ResNet101进行人脸识别的输出视图。但仍需自己实现对齐。
    resnetON = yes，关闭 resizeCNN，重设 cnnSize 为224，设置裁剪模型 crop_models，
                    对每个头部模型产生的最后一张视图进行224 × 224的裁剪
             = no，不做224的裁剪，按配置文件的cnnSize输出视图 [当前]
"""
## In case we want to crop the final image for each pose specified above/
## Each bbox should be [tlx,tly,brx,bry]
resizeCNN = opts.getboolean('general', 'resizeCNN')
cnnSize = opts.getint('general', 'cnnSize')
if not opts.getboolean('general', 'resnetON'):
    crop_models = [None,None,None,None,None]  # <-- with this no crop is done.     
else:
    #In case we want to produce images for ResNet
    resizeCNN=False #We can decide to resize it later using the CNN software or now here.
    ## The images produced without resizing could be useful to provide a reference system for in-plane alignment
    cnnSize=224
    crop_models = [[23,0,23+125,160],[0,0,210,230],[0,0,210,230]]  # <-- best crop for ResNet     


def demo():
    # 每种3d头部模型的总个数：10
    nSub = opts.getint('general', 'nTotSub')
    # fileList 记录了输入图像文件所在目录、文件名、用到的特征点提取数据模型文件名; outputFolder 为 /output/
    fileList, outputFolder = myutil.parse(sys.argv)
    # check for dlib saved weights for face landmark detection
    # if it fails, dowload and extract it manually from
    # http://sourceforge.net/projects/dclib/files/d.10/shape_predictor_68_face_landmarks.dat.bz2
    # 检查是否已有dlib库的特征点检测数据模型文件, 若没有则下载并解压到dlib模块文件目录下
    check.check_dlib_landmark_weights()
    ## Preloading all the models for speed
    # 预加载所有的头部模型
    allModels = myutil.preload(this_path,pose_models_folder,pose_models,nSub)

    for f in fileList:
        # 跳过注释（--batch 的情况）
        if '#' in f: #skipping comments
            continue
        splitted = f.split(',')
        image_key = splitted[0]
        image_path = splitted[1]
        image_landmarks = splitted[2]
        img = cv2.imread(image_path, 1)
        if image_landmarks != "None":
            lmark = np.loadtxt(image_landmarks)
            lmarks=[]
            lmarks.append(lmark)
        else:
            print '> Detecting landmarks'
            # lmarks = feature_detection.get_landmarks(img, this_path)
            ## 个人修改：
            lmarks = feature_detection.get_landmarks(img, this_path, image_path, write2File = True)

        if len(lmarks) != 0:
            ## Copy back original image and flipping image in case we need
            ## This flipping is performed using all the model or all the poses
            ## To refine the estimation of yaw. Yaw can change from model to model...
            img_display = img.copy()
            # 当 yaw < 0 时, 将图像水平翻转, 修改特征点集; 否则, 返回输入图像和原特征点集
            img, lmarks, yaw = myutil.flipInCase(img,lmarks,allModels)
            listPose = myutil.decidePose(yaw,opts, newModels)
            ## Looping over the poses
            for poseId in listPose:
            	posee = pose_models[poseId]
                ## Looping over the subjects
                for subj in range(1,nSub+1):
                    pose =   posee + '_' + str(subj).zfill(2) +'.mat'
                    print '> Looking at file: ' + image_path + ' with ' + pose
                    # load detections performed by dlib library on 3D model and Reference Image
                    print "> Using pose model in " + pose
                    ## Indexing the right model instead of loading it each time from memory.
                    model3D = allModels[pose]
                    eyemask = model3D.eyemask
                    # perform camera calibration according to the first face detected
                    proj_matrix, camera_matrix, rmat, tvec = calib.estimate_camera(model3D, lmarks[0])
                    ## We use eyemask only for frontal
                    if not myutil.isFrontal(pose):
                        eyemask = None
                    ##### Main part of the code: doing the rendering #############
                    rendered_raw, rendered_sym, face_proj, background_proj, temp_proj2_out_2, sym_weight = renderer.render(img, proj_matrix,\
                                                                                             model3D.ref_U, eyemask, model3D.facemask, opts)
                    ########################################################

                    if myutil.isFrontal(pose):
                        rendered_raw = rendered_sym
                    ## Cropping if required by crop_models
                    rendered_raw = myutil.cropFunc(pose,rendered_raw,crop_models[poseId])
                    ## Resizing if required
                    if resizeCNN:
                        rendered_raw = cv2.resize(rendered_raw, ( cnnSize, cnnSize ), interpolation=cv2.INTER_CUBIC )
                    ## Saving if required
                    if opts.getboolean('general', 'saveON'):
                        subjFolder = outputFolder + '/'+ image_key.split('_')[0]
                        myutil.mymkdir(subjFolder)
                        savingString = subjFolder +  '/' + image_key +'_rendered_'+ pose[8:-7]+'_'+str(subj).zfill(2)+'.jpg'
                        cv2.imwrite(savingString,rendered_raw)
                    					    	
                    ## Plotting if required
                    if opts.getboolean('general', 'plotON'):
                        myutil.show(img_display, img, lmarks, rendered_raw, \
                        face_proj, background_proj, temp_proj2_out_2, sym_weight)
        else:
            print '> Landmark not detected for this image...'  

if __name__ == "__main__":
    demo()
