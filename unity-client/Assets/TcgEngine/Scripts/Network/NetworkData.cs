using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine
{
    /// <summary>
    /// Main config file for all network-related things
    /// Server API password is not in this file (and is in the Server scene instead) to prevent exposing it to client build
    /// </summary>

    [CreateAssetMenu(fileName = "NetworkData", menuName = "TcgEngine/NetworkData", order = 0)]
    public class NetworkData : ScriptableObject
    {
        [Header("Game Server")]
        public string url;                      //Url of your Game Server
        public ushort port;                     //Port to connect/listen on your game server

        [Header("API")]
        public string api_url;                  //Url of your Nodejs API (can be same as Game Server)
        public bool api_https;                  //Http or Https ?   Http will use port 80,  https will use port 443

        [Header("Settings")]
        public SoloType solo_type;              //Wether to use Netcode or not in Solo mode (multiplayer always use netcode), using Netcode means more consistency between the 2 modes
        public AuthenticatorType auth_type;     //Test Mode (local mode) or API mode
        
        public static NetworkData Get()
        {
            return TcgNetwork.Get().data;
        }
    }

    public enum SoloType
    {
        UseNetcode = 0,     //Use Netcode network messages in solo to have more similar behavior on both multiplayer and solo, Recommended for consistency between multi/solo
        Offline = 10        //Make solo totally offline (no netcode) but may behave differently than multiplayer, required for WebGL since StartHost don't work on webgl.
    }
}
