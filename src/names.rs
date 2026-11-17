//! String names ↔ tuning enums, shared by the wasm and C boundaries.

use crate::tuning::{Degree, Genus, Shading, SymbolDrop};

pub fn parse_degree(s: &str) -> Option<Degree> {
    match s {
        "Ni" => Some(Degree::Ni),
        "Pa" => Some(Degree::Pa),
        "Vou" => Some(Degree::Vou),
        "Ga" => Some(Degree::Ga),
        "Di" => Some(Degree::Di),
        "Ke" => Some(Degree::Ke),
        "Zo" => Some(Degree::Zo),
        _ => None,
    }
}

pub fn parse_genus(s: &str) -> Option<Genus> {
    match s {
        "Diatonic" => Some(Genus::Diatonic),
        "Western" => Some(Genus::Western),
        "HardChromatic" => Some(Genus::HardChromatic),
        "SoftChromatic" => Some(Genus::SoftChromatic),
        "GraveDiatonic" => Some(Genus::GraveDiatonic),
        "EnharmonicZo" => Some(Genus::EnharmonicZo),
        "EnharmonicGa" => Some(Genus::EnharmonicGa),
        "Chromatic12" => Genus::equal_temperament(12),
        "Chromatic24" => Genus::equal_temperament(24),
        _ => None,
    }
}

pub fn parse_shading(s: &str) -> Option<Shading> {
    match s {
        "Zygos" => Some(Shading::Zygos),
        "Kliton" => Some(Shading::Kliton),
        "Spathi" | "SpathiKe" | "SpathiGa" => Some(Shading::Spathi),
        "Enharmonic" => Some(Shading::Enharmonic),
        _ => None,
    }
}

pub fn parse_symbol_drop(json: &str) -> Option<SymbolDrop> {
    #[derive(serde::Deserialize)]
    #[serde(tag = "type")]
    enum JsDrop {
        #[serde(rename = "pthora")]
        Pthora {
            genus: String,
            degree: String,
            #[serde(default)]
            phase: Option<u8>,
            #[serde(rename = "dropMoria")]
            drop_moria: i32,
            #[serde(rename = "dropDegree")]
            drop_degree: String,
        },
        #[serde(rename = "shading")]
        Shading {
            shading: String,
            #[serde(rename = "dropMoria")]
            drop_moria: i32,
            #[serde(rename = "dropDegree")]
            drop_degree: String,
        },
    }

    let drop = serde_json::from_str::<JsDrop>(json).ok()?;
    let symbol_drop = match drop {
        JsDrop::Pthora {
            genus,
            degree,
            phase,
            drop_moria,
            drop_degree,
        } => {
            let genus = parse_genus(&genus)?;
            let target_degree = parse_degree(&degree)?;
            let drop_degree = parse_degree(&drop_degree)?;
            SymbolDrop::Pthora {
                drop_moria,
                drop_degree,
                genus,
                target_degree,
                target_phase: phase,
            }
        }
        JsDrop::Shading {
            shading,
            drop_moria,
            drop_degree,
        } => {
            let drop_degree = parse_degree(&drop_degree)?;
            match shading.as_str() {
                "" => SymbolDrop::ClearChroa {
                    drop_moria,
                    drop_degree,
                },
                "DiesisGeniki" => SymbolDrop::Geniki {
                    drop_moria,
                    drop_degree,
                    shift: 6,
                },
                "YfesisGeniki" => SymbolDrop::Geniki {
                    drop_moria,
                    drop_degree,
                    shift: -6,
                },
                _ => {
                    let symbol = parse_shading(&shading)?;
                    SymbolDrop::Chroa {
                        drop_moria,
                        drop_degree,
                        symbol,
                    }
                }
            }
        }
    };
    Some(symbol_drop)
}

/// A user-defined closed octave scale (e.g. a raga preset): exactly 7 positive
/// moria steps from `canonical_root` summing to 72. Anything else is rejected
/// rather than silently becoming a tiled generator.
pub fn parse_custom_genus(name: &str, intervals_json: &str, canonical_root: &str) -> Option<Genus> {
    let canonical_root = parse_degree(canonical_root)?;
    let intervals = serde_json::from_str::<Vec<i32>>(intervals_json).ok()?;
    if intervals.len() != 7
        || intervals.iter().any(|&s| s <= 0)
        || intervals.iter().sum::<i32>() != 72
    {
        return None;
    }
    Some(Genus::Custom {
        name: name.to_string(),
        intervals,
        canonical_root,
    })
}
