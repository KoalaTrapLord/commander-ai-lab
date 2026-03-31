using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine.Client
{
    /// <summary>
    /// Component added to a scene to add some generic sfx/music to the arena
    /// </summary>

    public class SceneSettings : MonoBehaviour
    {
        public AudioClip start_audio;
        public AudioClip[] game_music;
        public AudioClip[] game_ambience;

        private static SceneSettings instance;

        private void Awake()
        {
            instance = this;
        }

        void Start()
        {
            AudioTool.Get().PlaySFX("game_sfx", start_audio);
            if (game_music.Length > 0)
                AudioTool.Get().PlayMusic("music", game_music[Random.Range(0, game_music.Length)]);
            if (game_ambience.Length > 0)
                AudioTool.Get().PlaySFX("ambience", game_ambience[Random.Range(0, game_ambience.Length)], 0.5f, true);
        }

        void Update()
        {

        }

        public static SceneSettings Get()
        {
            return instance;
        }
    }
}
