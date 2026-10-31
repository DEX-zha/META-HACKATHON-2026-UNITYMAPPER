using System;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;

namespace HdrpAgent.Runtime
{
    // Capture conditions only. No reference object, material or light transforms.
    [Serializable]public sealed class ReferenceRenderProtocol
    {
        public string schema_version="1.1",render_path,unity_version,graphics_api,pipeline_asset;
        public bool hdr,physical_camera,custom_frame_settings,dynamic_resolution;
        public float near_clip,far_clip,focal_length;
        public float[] sensor_size,lens_shift,viewport,background_rgba;
        public int gate_fit,culling_mask,volume_layer_mask;
        public string clear_mode,anti_aliasing,frame_settings,frame_overrides,exposure_mode,tonemapping_mode;
        public static ReferenceRenderProtocol Read(Camera camera,string path){
            var hd=camera.GetComponent<HDAdditionalCameraData>();if(hd==null)throw new InvalidOperationException("HDRP camera protocol unavailable");
            var stack=HDCamera.GetOrCreate(camera).volumeStack;
            return new ReferenceRenderProtocol{
                render_path=path,unity_version=Application.unityVersion,graphics_api=SystemInfo.graphicsDeviceType.ToString(),pipeline_asset=GraphicsSettings.currentRenderPipeline?.name,
                hdr=camera.allowHDR,physical_camera=camera.usePhysicalProperties,custom_frame_settings=hd.customRenderingSettings,dynamic_resolution=hd.allowDynamicResolution,
                near_clip=camera.nearClipPlane,far_clip=camera.farClipPlane,focal_length=camera.focalLength,
                sensor_size=new[]{camera.sensorSize.x,camera.sensorSize.y},lens_shift=new[]{camera.lensShift.x,camera.lensShift.y},viewport=new[]{camera.rect.x,camera.rect.y,camera.rect.width,camera.rect.height},
                background_rgba=new[]{hd.backgroundColorHDR.r,hd.backgroundColorHDR.g,hd.backgroundColorHDR.b,hd.backgroundColorHDR.a},
                gate_fit=(int)camera.gateFit,culling_mask=camera.cullingMask,volume_layer_mask=hd.volumeLayerMask.value,clear_mode=hd.clearColorMode.ToString(),anti_aliasing=hd.antialiasing.ToString(),
                frame_settings=JsonUtility.ToJson(hd.renderingPathCustomFrameSettings),frame_overrides=JsonUtility.ToJson(hd.renderingPathCustomFrameSettingsOverrideMask),
                exposure_mode=stack.GetComponent<Exposure>()?.mode.value.ToString(),tonemapping_mode=stack.GetComponent<Tonemapping>()?.mode.value.ToString()
            };
        }
        public static void Apply(Camera camera,ReferenceRenderProtocol protocol){
            var hd=camera.GetComponent<HDAdditionalCameraData>();if(hd==null)throw new InvalidOperationException("HDRP camera required");
            camera.allowHDR=protocol.hdr;camera.usePhysicalProperties=protocol.physical_camera;camera.nearClipPlane=protocol.near_clip;camera.farClipPlane=protocol.far_clip;
            camera.sensorSize=new Vector2(protocol.sensor_size[0],protocol.sensor_size[1]);camera.lensShift=new Vector2(protocol.lens_shift[0],protocol.lens_shift[1]);camera.focalLength=protocol.focal_length;
            camera.rect=new Rect(protocol.viewport[0],protocol.viewport[1],protocol.viewport[2],protocol.viewport[3]);camera.gateFit=(Camera.GateFitMode)protocol.gate_fit;camera.cullingMask=protocol.culling_mask;
            hd.volumeLayerMask=protocol.volume_layer_mask;hd.clearColorMode=(HDAdditionalCameraData.ClearColorMode)Enum.Parse(typeof(HDAdditionalCameraData.ClearColorMode),protocol.clear_mode);
            hd.allowDynamicResolution=false;hd.antialiasing=HDAdditionalCameraData.AntialiasingMode.None;hd.customRenderingSettings=protocol.custom_frame_settings;
            hd.renderingPathCustomFrameSettings=JsonUtility.FromJson<FrameSettings>(protocol.frame_settings);hd.renderingPathCustomFrameSettingsOverrideMask=JsonUtility.FromJson<FrameSettingsOverrideMask>(protocol.frame_overrides);
            if(protocol.background_rgba!=null&&protocol.background_rgba.Length==4)hd.backgroundColorHDR=new Color(protocol.background_rgba[0],protocol.background_rgba[1],protocol.background_rgba[2],protocol.background_rgba[3]);
        }
    }
}
