using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEditor;
using System.Linq;
using UnityEditor.PackageManager.Requests;
using System.Threading.Tasks;
using System;

namespace TcgEngine.EditorTool
{
    /// <summary>
    /// Add symbols and sorting layers
    /// </summary>

    [InitializeOnLoad]
    public class ImportPackage
    {
        private const string import_done = "import_completed";

        static ImportPackage()
        {
            AfterCompile();
        }

        static void AfterCompile()
        {
            if(!SessionState.GetBool(import_done, false))
            {
                SessionState.SetBool(import_done, true);

                //Add TCG_ENGINE symbol
                string symbolSEO = "TCG_ENGINE";
                if (!HasSymbol(symbolSEO))
                {
                    AddSymbol(symbolSEO);
                }

                //Add Sorting Layer
                AddSortingLayer(3127249329, "UI");

                //Check version
                FindNetcodeVersion();
            }
        }

        private static void AddSortingLayer(long id, string title)
        {
            SerializedObject tagsAndLayersManager = new SerializedObject(AssetDatabase.LoadAssetAtPath<UnityEngine.Object>("ProjectSettings/TagManager.asset"));
            SerializedProperty sortingLayersProp = tagsAndLayersManager.FindProperty("m_SortingLayers");

            for (int i = 0; i < sortingLayersProp.arraySize; i++)
            {
                SerializedProperty layer = sortingLayersProp.GetArrayElementAtIndex(i);
                if (layer.FindPropertyRelative("uniqueID").longValue == id)
                    return; //Already there
            }

            //Add layer
            sortingLayersProp.InsertArrayElementAtIndex(sortingLayersProp.arraySize);
            SerializedProperty newlayer = sortingLayersProp.GetArrayElementAtIndex(sortingLayersProp.arraySize - 1);
            newlayer.FindPropertyRelative("uniqueID").longValue = id;
            newlayer.FindPropertyRelative("name").stringValue = title;
            tagsAndLayersManager.ApplyModifiedProperties();
            Debug.Log("Added " + title + " layer to Sorting Layers"); 
        }

        private async static void FindNetcodeVersion()
        {
            SearchRequest req = UnityEditor.PackageManager.Client.Search("com.unity.netcode.gameobjects");
            while (!req.IsCompleted)
            {
                await TimeTool.Delay(100); 
            }

            UnityEditor.PackageManager.PackageInfo[] infos = req.Result;
            foreach (UnityEditor.PackageManager.PackageInfo info in infos)
            {
                Version vers = new Version(info.version);
                Version vers2 = new Version("1.2.0");
                if(vers.CompareTo(vers2) < 0) 
                    Debug.LogError("Netcode version must be at least 1.2.0 to use TcgEngine");
            }
        }


#if UNITY_2020
        private static void AddSymbol(string symbol)
        {
            BuildTargetGroup build_group = BuildPipeline.GetBuildTargetGroup(EditorUserBuildSettings.activeBuildTarget);
            string defines_string = UnityEditor.PlayerSettings.GetScriptingDefineSymbolsForGroup(build_group);
            List<string> all_defines = defines_string.Split(';').ToList();
            string[] symbols = new string[] { symbol };
            all_defines.AddRange(symbols.Except(all_defines));
            UnityEditor.PlayerSettings.SetScriptingDefineSymbolsForGroup(build_group, string.Join(";", all_defines.ToArray()));
            Debug.Log("Added " + symbol + " to the Scripting Define Symbols");
        }

        private static bool HasSymbol(string symbol)
        {
            BuildTargetGroup build_group = BuildPipeline.GetBuildTargetGroup(EditorUserBuildSettings.activeBuildTarget);
            string definesString = UnityEditor.PlayerSettings.GetScriptingDefineSymbolsForGroup(build_group);
            List<string> allDefines = definesString.Split(';').ToList();
            return allDefines.Contains(symbol);
        }
#else
        private static void AddSymbol(string symbol)
        {
            UnityEditor.Build.NamedBuildTarget target = GetActiveNamedTarget();
            string defines_string = UnityEditor.PlayerSettings.GetScriptingDefineSymbols(target);
            List<string> all_defines = defines_string.Split(';').ToList();
            string[] symbols = new string[] { symbol };
            all_defines.AddRange(symbols.Except(all_defines));
            UnityEditor.PlayerSettings.SetScriptingDefineSymbols(target, string.Join(";", all_defines.ToArray()));
            Debug.Log("Added " + symbol + " to the Scripting Define Symbols");
        }

        private static bool HasSymbol(string symbol)
        {
            UnityEditor.Build.NamedBuildTarget target = GetActiveNamedTarget();
            string defines_string = UnityEditor.PlayerSettings.GetScriptingDefineSymbols(target);
            List<string> allDefines = defines_string.Split(';').ToList();
            return allDefines.Contains(symbol);
        }

        private static UnityEditor.Build.NamedBuildTarget GetActiveNamedTarget()
        {
            BuildTargetGroup buildTargetGroup = BuildPipeline.GetBuildTargetGroup(EditorUserBuildSettings.activeBuildTarget);

            if (buildTargetGroup == BuildTargetGroup.Standalone && EditorUserBuildSettings.standaloneBuildSubtarget == StandaloneBuildSubtarget.Server)
            {
                return UnityEditor.Build.NamedBuildTarget.Server;
            }

            return UnityEditor.Build.NamedBuildTarget.FromBuildTargetGroup(buildTargetGroup);
        }
#endif
    }
}