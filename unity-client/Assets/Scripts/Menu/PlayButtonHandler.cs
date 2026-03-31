using UnityEngine;
using CommanderAILab.Tabletop;

public class PlayButtonHandler : MonoBehaviour
{
    public void OnClickPlay()
    {
        CommanderGameBridge.LoadSimulator();
    }
}