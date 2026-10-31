using UnityEngine;
namespace HdrpAgent.Runtime
{
    [DisallowMultipleComponent]
    public sealed class CaptureBinding:MonoBehaviour
    {
        [SerializeField]public string logicalKey;
        [SerializeField]public string sourceGlobalObjectId;
        [SerializeField]public string workingGlobalObjectId;
    }
}
