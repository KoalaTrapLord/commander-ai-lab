using System.Collections;
using System.Collections.Generic;
using Unity.Netcode.Transports.UTP;
using UnityEngine;

namespace TcgEngine
{
    //Just a wrapper of UnityTransport to make it easier to replace with WebSocketTransport if planning to build for WebGL

    public class TcgTransport : MonoBehaviour
    {
        //[Header("Client")]
        //public string domain;               //May be the same as NetworkData url, but on webgl since DNS resolve doesn't work, you need to set the ssl domain here but the IP on NetworkData
        //[TextArea] public string chain;

        //[Header("Server")]
        //[TextArea] public string cert;
        //[TextArea] public string key;         //Set this on server scene only, otherwise you will expose the key on the client build

        private UnityTransport transport;

        private const string listen_all = "0.0.0.0";

        public virtual void Init()
        {
            transport = GetComponent<UnityTransport>();
        }

        public virtual void SetServer(ushort port)
        {
            transport.SetConnectionData(listen_all, port, listen_all);
            //transport.SetServerSecrets(cert, key);
        }

        public virtual void SetClient(string address, ushort port)
        {
            string ip = NetworkTool.HostToIP(address);          //This line doesn't work on WebGL, address will be unchanged
            transport.SetConnectionData(ip, port);
            //transport.SetClientSecrets(address, chain);       //Use this line for most platforms, same address as NetworkData, use domain name (not IP) on NetworkData url
            //transport.SetClientSecrets(domain, chain);        //Use this line for WebGL, since you will put IP on the NetworkData, and ssl domain name here
        }

        public virtual string GetAddress() { return transport.ConnectionData.Address; }
        public virtual ushort GetPort() { return transport.ConnectionData.Port; }
    }
}
