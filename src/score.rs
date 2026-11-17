//! MusicXML → the practice note model.
//!
//! A port of `training-prototype/js/model.js` (parse, lyric propagation, verse
//! selection) plus the section markers from `js/sections.js`, so native hosts
//! practise from exactly the notes the web app does.
//!
//! Deliberately not handled, as on the web: repeats and voltas, tempo marks,
//! `<transpose>`, time signatures. Beats are quarter notes from the start.

use roxmltree::{Document, Node, ParsingOptions};
use std::collections::HashMap;

#[derive(Clone, Debug, PartialEq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Note {
    pub midi: i32,
    pub start_beat: f64,
    pub dur_beat: f64,
    /// Printed measure number.
    pub measure: i32,
    /// Syllable for the selected verse; a trailing "-" continues the word.
    pub lyric: Option<String>,
    /// The syllable is this part's own text (printed under its staff), not
    /// one borrowed from another part for the practice lane.
    pub own_lyric: bool,
    #[serde(skip)]
    lyric_verses: HashMap<u32, String>,
}

/// A notehead as engraved.
#[derive(Clone, Debug, PartialEq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Head {
    /// Diatonic position: `octave * 7 + step` with C = 0 (so C4 is 28, E4 is 30).
    pub pos: i32,
    /// Printed accidental, as MusicXML names it ("sharp", "flat", "natural", ...).
    pub accidental: Option<String>,
    pub tie_start: bool,
    pub tie_stop: bool,
    /// Index into the part's `notes`; a tied continuation points at the note it extends.
    pub note: usize,
}

/// A note, chord or rest as engraved.
#[derive(Clone, Debug, PartialEq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Event {
    pub start_beat: f64,
    pub dur_beat: f64,
    /// "breve", "whole", "half", "quarter", "eighth" or "16th".
    pub kind: String,
    pub dots: u8,
    /// Stem direction when the engraving gives one.
    pub stem_up: Option<bool>,
    /// Beam state per level (level 1 first): "begin", "continue", "end",
    /// "forward hook" or "backward hook".
    pub beams: Vec<String>,
    /// Empty for a rest.
    pub heads: Vec<Head>,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Clef {
    /// "G", "F" or "C".
    pub sign: String,
    pub line: i32,
    /// -1 for a treble clef sounding an octave lower (tenor).
    pub octave_change: i32,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct TimeSignature {
    pub beats: String,
    pub beat_type: String,
    /// False for chant engraved in free rhythm (the signature is not printed).
    pub visible: bool,
}

/// One measure of one staff, with only the attributes that change in it.
#[derive(Clone, Debug, PartialEq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct StaffMeasure {
    pub number: i32,
    pub start_beat: f64,
    pub end_beat: f64,
    pub clef: Option<Clef>,
    pub fifths: Option<i32>,
    pub time: Option<TimeSignature>,
    /// Right barline: "regular", "none", "light-light", "light-heavy", ...
    pub barline: String,
    /// The source engraving starts a new line here.
    pub new_system: bool,
    pub events: Vec<Event>,
}

/// Note value for a duration when the file does not name one.
fn kind_for(dur_beat: f64) -> (&'static str, u8) {
    const KINDS: [(&str, f64); 6] = [
        ("breve", 8.0),
        ("whole", 4.0),
        ("half", 2.0),
        ("quarter", 1.0),
        ("eighth", 0.5),
        ("16th", 0.25),
    ];
    for (name, beats) in KINDS {
        if dur_beat >= beats * 1.5 - 1e-6 && dur_beat < beats * 2.0 - 1e-6 {
            return (name, 1);
        }
        if dur_beat >= beats - 1e-6 {
            return (name, 0);
        }
    }
    ("16th", 0)
}

fn step_index(step: &str) -> i32 {
    "CDEFGAB".find(step).map_or(0, |i| i as i32)
}

#[derive(Clone, Debug, PartialEq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Part {
    /// "S", "A", "T", "B", or "P<index>" beyond the fourth part.
    pub voice_key: String,
    pub voice_name: String,
    pub index: usize,
    pub notes: Vec<Note>,
    /// The part as engraved, measure by measure.
    pub staff: Vec<StaffMeasure>,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize)]
pub struct Section {
    pub title: String,
    pub measure: i32,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Score {
    pub parts: Vec<Part>,
    pub measure_count: usize,
    /// Highest lyric verse number present (1 when there is a single text).
    pub max_verse: u32,
    /// Rehearsal headings printed above the top part; empty unless there are two or more.
    pub sections: Vec<Section>,
}

#[derive(Debug, PartialEq, Eq)]
pub struct ParseError(pub String);

const VOICES: [(&str, &str); 4] = [
    ("S", "Soprano"),
    ("A", "Alto"),
    ("T", "Tenor"),
    ("B", "Bass"),
];

/// JS `parseInt`: optional sign and leading digits, ignoring what follows.
fn parse_int(s: &str) -> Option<i32> {
    let s = s.trim_start();
    let (sign, digits) = match s.strip_prefix('-') {
        Some(rest) => (-1, rest),
        None => (1, s.strip_prefix('+').unwrap_or(s)),
    };
    let end = digits
        .find(|c: char| !c.is_ascii_digit())
        .unwrap_or(digits.len());
    digits[..end].parse::<i32>().ok().map(|n| sign * n)
}

fn first<'a, 'i>(node: Node<'a, 'i>, tag: &str) -> Option<Node<'a, 'i>> {
    node.descendants()
        .find(|n| n.is_element() && n.tag_name().name() == tag && *n != node)
}

fn all<'a, 'i: 'a>(node: Node<'a, 'i>, tag: &'a str) -> impl Iterator<Item = Node<'a, 'i>> + 'a {
    node.descendants()
        .filter(move |n| n.is_element() && n.tag_name().name() == tag && *n != node)
}

/// Trimmed text content of the first `tag` descendant.
fn text_of(node: Node, tag: &str) -> Option<String> {
    first(node, tag).map(|n| {
        n.descendants()
            .filter(|d| d.is_text())
            .filter_map(|d| d.text())
            .collect::<String>()
            .trim()
            .to_string()
    })
}

fn step_semitone(step: &str) -> Option<i32> {
    Some(match step {
        "C" => 0,
        "D" => 2,
        "E" => 4,
        "F" => 5,
        "G" => 7,
        "A" => 9,
        "B" => 11,
        _ => return None,
    })
}

/// Alteration the key signature gives a step: +1 sharp, -1 flat.
fn key_alter(fifths: i32, step: &str) -> i32 {
    const SHARPS: [&str; 7] = ["F", "C", "G", "D", "A", "E", "B"];
    const FLATS: [&str; 7] = ["B", "E", "A", "D", "G", "C", "F"];
    if fifths > 0 && SHARPS[..(fifths as usize).min(7)].contains(&step) {
        1
    } else if fifths < 0 && FLATS[..(-fifths as usize).min(7)].contains(&step) {
        -1
    } else {
        0
    }
}

fn syllable(lyric: Node) -> Option<String> {
    let text = text_of(lyric, "text").filter(|t| !t.is_empty())?;
    Some(match text_of(lyric, "syllabic").as_deref() {
        Some("begin") | Some("middle") => text + "-",
        _ => text,
    })
}

/// Parse a MusicXML document and select `verse` (1-based) for the lyrics.
pub fn parse(xml: &str, verse: u32) -> Result<Score, ParseError> {
    let options = ParsingOptions {
        allow_dtd: true,
        ..ParsingOptions::default()
    };
    let doc = Document::parse_with_options(xml, options).map_err(|e| ParseError(e.to_string()))?;
    let root = doc.root();

    let part_names: HashMap<&str, String> = all(root, "score-part")
        .filter_map(|sp| {
            Some((
                sp.attribute("id")?,
                text_of(sp, "part-name").unwrap_or_default(),
            ))
        })
        .collect();

    let mut measure_count = 0;
    let mut max_verse = 1;
    let mut sections = Vec::new();

    let mut parts: Vec<Part> = all(root, "part")
        .enumerate()
        .map(|(index, part_node)| {
            let name = part_node
                .attribute("id")
                .and_then(|id| part_names.get(id))
                .filter(|n| !n.is_empty())
                .cloned()
                .unwrap_or_else(|| format!("Part {}", index + 1));
            // Match to SATB by name, else by position.
            let lower = name.to_lowercase();
            let (voice_key, voice_name) = VOICES
                .iter()
                .find(|(_, voice)| lower.starts_with(&voice.to_lowercase()))
                .or(VOICES.get(index))
                .map(|(k, v)| (k.to_string(), v.to_string()))
                .unwrap_or_else(|| (format!("P{index}"), name.clone()));

            let mut divisions = 1.0;
            let mut fifths = 0;
            let mut notes: Vec<Note> = Vec::new();
            let mut beat = 0.0;
            // Onset of the last pitched note; chord followers share it.
            let mut last_onset: Option<f64> = None;

            let mut staff: Vec<StaffMeasure> = Vec::new();
            let measures: Vec<Node> = all(part_node, "measure").collect();
            measure_count = measure_count.max(measures.len());

            for (m_idx, measure_node) in measures.iter().enumerate() {
                let measure = measure_node
                    .attribute("number")
                    .and_then(parse_int)
                    .filter(|n| *n != 0)
                    .unwrap_or(m_idx as i32 + 1);
                let (mut new_clef, mut new_fifths, mut new_time) = (None, None, None);
                for attributes in all(*measure_node, "attributes") {
                    if let Some(d) = text_of(attributes, "divisions")
                        .as_deref()
                        .and_then(parse_int)
                        .filter(|d| *d > 0)
                    {
                        divisions = d as f64;
                    }
                    if let Some(f) = text_of(attributes, "fifths").as_deref().and_then(parse_int) {
                        fifths = f;
                        new_fifths = Some(f);
                    }
                    if let Some(clef) = first(attributes, "clef") {
                        new_clef = Some(Clef {
                            sign: text_of(clef, "sign").unwrap_or_else(|| "G".into()),
                            line: text_of(clef, "line")
                                .as_deref()
                                .and_then(parse_int)
                                .unwrap_or(2),
                            octave_change: text_of(clef, "clef-octave-change")
                                .as_deref()
                                .and_then(parse_int)
                                .unwrap_or(0),
                        });
                    }
                    if let Some(time) = first(attributes, "time") {
                        new_time = Some(TimeSignature {
                            beats: text_of(time, "beats").unwrap_or_default(),
                            beat_type: text_of(time, "beat-type").unwrap_or_default(),
                            visible: time.attribute("print-object") != Some("no"),
                        });
                    }
                }
                let mut events: Vec<Event> = Vec::new();
                if index == 0 {
                    // First heading printed above the staff in this measure.
                    let heading = all(*measure_node, "direction")
                        .filter(|d| d.attribute("placement") == Some("above"))
                        .filter_map(|d| text_of(d, "words"))
                        .find(|w| !w.is_empty());
                    if let Some(title) = heading {
                        sections.push(Section { title, measure });
                    }
                }

                let measure_start = beat;
                // Accidentals hold for the rest of the measure, per step and octave.
                let mut local_alter: HashMap<(String, i32), i32> = HashMap::new();
                let duration = |n: Node| {
                    text_of(n, "duration")
                        .as_deref()
                        .and_then(parse_int)
                        .unwrap_or(0) as f64
                        / divisions
                };

                for child in measure_node.children().filter(Node::is_element) {
                    match child.tag_name().name() {
                        "backup" => beat -= duration(child),
                        "forward" => beat += duration(child),
                        "note" => {
                            let is_chord = first(child, "chord").is_some();
                            let dur_beat = duration(child);
                            let onset = if is_chord {
                                last_onset.unwrap_or(beat)
                            } else {
                                beat
                            };
                            let is_rest = first(child, "rest").is_some();
                            let pitch = if is_rest { None } else { first(child, "pitch") };
                            let printed = child.attribute("print-object") != Some("no");
                            let (fallback_kind, fallback_dots) = kind_for(dur_beat);
                            let new_event = || Event {
                                start_beat: onset,
                                dur_beat,
                                kind: text_of(child, "type")
                                    .filter(|t| !t.is_empty())
                                    .unwrap_or_else(|| fallback_kind.to_string()),
                                dots: match all(child, "dot").count() as u8 {
                                    0 if first(child, "type").is_none() => fallback_dots,
                                    n => n,
                                },
                                stem_up: match text_of(child, "stem").as_deref() {
                                    Some("up") => Some(true),
                                    Some("down") => Some(false),
                                    _ => None,
                                },
                                beams: {
                                    let mut beams: Vec<(i32, String)> = child
                                        .children()
                                        .filter(|n| n.is_element() && n.tag_name().name() == "beam")
                                        .map(|b| {
                                            (
                                                b.attribute("number")
                                                    .and_then(parse_int)
                                                    .unwrap_or(1),
                                                b.text().unwrap_or("").trim().to_string(),
                                            )
                                        })
                                        .collect();
                                    beams.sort_by_key(|(level, _)| *level);
                                    beams.into_iter().map(|(_, state)| state).collect()
                                },
                                heads: Vec::new(),
                            };
                            if is_rest && printed && dur_beat > 0.0 {
                                events.push(new_event());
                            }
                            if let Some(pitch) = pitch {
                                let step = text_of(pitch, "step").unwrap_or_default();
                                let octave =
                                    text_of(pitch, "octave").as_deref().and_then(parse_int);
                                if let (Some(semitone), Some(octave)) =
                                    (step_semitone(&step), octave)
                                {
                                    let key = (step.clone(), octave);
                                    let alter = match text_of(pitch, "alter")
                                        .as_deref()
                                        .and_then(parse_int)
                                    {
                                        Some(alter) => {
                                            local_alter.insert(key, alter);
                                            alter
                                        }
                                        None => local_alter
                                            .get(&key)
                                            .copied()
                                            .unwrap_or_else(|| key_alter(fifths, &step)),
                                    };
                                    let midi = 12 * (octave + 1) + semitone + alter;

                                    // Verse 1 is an unnumbered or number="1" lyric only: on
                                    // multilingual scores, borrowing another verse's element
                                    // would interleave languages.
                                    let mut lyric_verses: HashMap<u32, String> = HashMap::new();
                                    for lyric in all(child, "lyric") {
                                        let number = lyric
                                            .attribute("number")
                                            .filter(|n| !n.is_empty())
                                            .map_or(1, |n| {
                                                parse_int(n).filter(|v| *v > 0).unwrap_or(1) as u32
                                            });
                                        if let Some(syllable) = syllable(lyric) {
                                            max_verse = max_verse.max(number);
                                            lyric_verses.entry(number).or_insert(syllable);
                                        } else if number == 1 {
                                            // The web takes the first verse-1 element even
                                            // when it is empty; a later one does not replace it.
                                            lyric_verses.entry(1).or_default();
                                        }
                                    }
                                    lyric_verses.retain(|_, s| !s.is_empty());

                                    // A tie stop continues a held note: extend it rather
                                    // than re-attacking.
                                    let tie_stop = all(child, "tie")
                                        .any(|t| t.attribute("type") == Some("stop"));
                                    let continued = if tie_stop {
                                        (notes.len().saturating_sub(8)..notes.len()).rev().find(
                                            |&k| {
                                                notes[k].midi == midi
                                                    && (notes[k].start_beat + notes[k].dur_beat
                                                        - onset)
                                                        .abs()
                                                        < 1e-6
                                            },
                                        )
                                    } else {
                                        None
                                    };
                                    let note_index = match continued {
                                        Some(k) => {
                                            notes[k].dur_beat += dur_beat;
                                            k
                                        }
                                        None => {
                                            notes.push(Note {
                                                midi,
                                                start_beat: onset,
                                                dur_beat,
                                                measure,
                                                lyric: None,
                                                own_lyric: false,
                                                lyric_verses,
                                            });
                                            notes.len() - 1
                                        }
                                    };
                                    if printed {
                                        let head = Head {
                                            pos: octave * 7 + step_index(&step),
                                            accidental: text_of(child, "accidental")
                                                .filter(|a| !a.is_empty()),
                                            tie_start: all(child, "tie")
                                                .any(|t| t.attribute("type") == Some("start")),
                                            tie_stop,
                                            note: note_index,
                                        };
                                        // A chord follower joins the note it sounds with.
                                        match events.last_mut() {
                                            Some(event)
                                                if is_chord
                                                    && !event.heads.is_empty()
                                                    && event.start_beat == onset =>
                                            {
                                                event.heads.push(head)
                                            }
                                            _ => {
                                                let mut event = new_event();
                                                event.heads.push(head);
                                                events.push(event);
                                            }
                                        }
                                    }
                                    last_onset = Some(onset);
                                }
                            }
                            if !is_chord {
                                beat += dur_beat;
                            }
                        }
                        _ => {}
                    }
                }
                // Keep measures contiguous even if a part under-fills.
                if beat < measure_start {
                    beat = measure_start;
                }
                staff.push(StaffMeasure {
                    number: measure,
                    start_beat: measure_start,
                    end_beat: beat,
                    clef: new_clef,
                    fifths: new_fifths,
                    time: new_time,
                    barline: all(*measure_node, "barline")
                        .filter(|b| b.attribute("location").unwrap_or("right") == "right")
                        .find_map(|b| text_of(b, "bar-style"))
                        .filter(|style| !style.is_empty())
                        .unwrap_or_else(|| "regular".to_string()),
                    new_system: first(*measure_node, "print").is_some_and(|p| {
                        p.attribute("new-system") == Some("yes")
                            || p.attribute("new-page") == Some("yes")
                    }),
                    events,
                });
            }

            Part {
                voice_key,
                voice_name,
                index,
                notes,
                staff,
            }
        })
        .collect();

    if sections.len() < 2 {
        sections.clear();
    }
    apply_verse(&mut parts, verse.max(1));
    Ok(Score {
        parts,
        measure_count,
        max_verse,
        sections,
    })
}

/// Put the chosen verse's syllables in `lyric`.
///
/// A note with no syllable for the verse falls back to verse 1 only when the
/// verse is a *partial* alternate (a refrain variant covering a phrase or two).
/// A *full* parallel verse (another language, syllabified differently) never
/// falls back: its gaps are real melismas. Coverage relative to verse 1 tells
/// the two apart; alternates sit near 4 %, full verses near 100 %.
fn apply_verse(parts: &mut [Part], verse: u32) {
    let count = |v: u32| {
        parts
            .iter()
            .flat_map(|p| &p.notes)
            .filter(|n| n.lyric_verses.contains_key(&v))
            .count()
    };
    let full_verse = verse != 1 && count(1) > 0 && count(verse) as f64 / count(1) as f64 >= 0.5;
    for note in parts.iter_mut().flat_map(|p| &mut p.notes) {
        note.lyric = match note.lyric_verses.get(&verse) {
            Some(syllable) => Some(syllable.clone()),
            None if !full_verse => note.lyric_verses.get(&1).cloned(),
            None => None,
        };
        note.own_lyric = note.lyric.is_some();
    }
    propagate_lyrics(parts);
}

/// Engravings often print shared text under one staff only. Parts with few
/// lyrics borrow from the best rhythm-matched lyric-bearing part, at exactly
/// matching onsets only, so differing rhythms never get wrong text.
fn propagate_lyrics(parts: &mut [Part]) {
    let key = |beat: f64| (beat * 1000.0).round() as i64;
    let has_own = |p: &Part| {
        let lyrics = p.notes.iter().filter(|n| n.lyric.is_some()).count();
        lyrics as f64 >= (p.notes.len() as f64 * 0.2).max(3.0)
    };
    let donors: Vec<HashMap<i64, String>> = parts
        .iter()
        .filter(|p| has_own(p))
        .map(|p| {
            p.notes
                .iter()
                .filter_map(|n| Some((key(n.start_beat), n.lyric.clone()?)))
                .collect()
        })
        .collect();
    for part in parts.iter_mut().filter(|p| !has_own(p)) {
        let hits = |d: &HashMap<i64, String>| {
            part.notes
                .iter()
                .filter(|n| d.contains_key(&key(n.start_beat)))
                .count()
        };
        // First donor with the most matches, as on the web.
        let mut best: Option<(&HashMap<i64, String>, usize)> = None;
        for donor in &donors {
            let h = hits(donor);
            if h > best.map_or(0, |(_, b)| b) {
                best = Some((donor, h));
            }
        }
        let Some((donor, _)) = best else { continue };
        for note in part.notes.iter_mut().filter(|n| n.lyric.is_none()) {
            note.lyric = donor.get(&key(note.start_beat)).cloned();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn note(step: &str, octave: i32, dur: i32, extra: &str) -> String {
        format!("<note><pitch><step>{step}</step><octave>{octave}</octave></pitch><duration>{dur}</duration>{extra}</note>")
    }

    fn doc(parts: &[(&str, &str)]) -> String {
        let list: String = parts
            .iter()
            .enumerate()
            .map(|(i, (name, _))| {
                format!("<score-part id=\"P{i}\"><part-name>{name}</part-name></score-part>")
            })
            .collect();
        let bodies: String = parts
            .iter()
            .enumerate()
            .map(|(i, (_, body))| format!("<part id=\"P{i}\">{body}</part>"))
            .collect();
        format!(
            "<?xml version=\"1.0\"?><!DOCTYPE score-partwise PUBLIC \"-//Recordare//DTD MusicXML 3.1 Partwise//EN\" \"http://www.musicxml.org/dtds/partwise.dtd\"><score-partwise><part-list>{list}</part-list>{bodies}</score-partwise>"
        )
    }

    const ATTRS: &str =
        "<attributes><divisions>2</divisions><key><fifths>1</fifths></key></attributes>";

    #[test]
    fn pitches_key_signature_and_measure_accidentals() {
        let sharp = "<note><pitch><step>C</step><alter>1</alter><octave>4</octave></pitch><duration>2</duration></note>";
        let body = format!(
            "<measure number=\"1\">{ATTRS}{}{}{}{}</measure><measure number=\"2\">{}</measure>",
            note("F", 4, 2, ""), // F# from the key
            sharp,
            note("C", 4, 2, ""), // still C# within the measure
            note("C", 5, 4, ""), // other octave: natural
            note("C", 4, 2, ""), // new measure: natural again
        );
        let score = parse(&doc(&[("Soprano", &body)]), 1).unwrap();
        let notes = &score.parts[0].notes;
        assert_eq!(
            notes.iter().map(|n| n.midi).collect::<Vec<_>>(),
            [66, 61, 61, 72, 60]
        );
        assert_eq!(
            notes.iter().map(|n| n.start_beat).collect::<Vec<_>>(),
            [0.0, 1.0, 2.0, 3.0, 5.0]
        );
        assert_eq!(notes[3].dur_beat, 2.0);
        assert_eq!(notes[4].measure, 2);
        assert_eq!(score.measure_count, 2);
    }

    #[test]
    fn ties_merge_rests_advance_chords_and_backup_share_time() {
        let body = format!(
            "<measure number=\"1\">{ATTRS}{}{}<note><rest/><duration>2</duration></note>{}{}<backup><duration>2</duration></backup>{}</measure>",
            note("G", 4, 2, "<tie type=\"start\"/>"),
            note("G", 4, 2, "<tie type=\"stop\"/>"),
            note("A", 4, 2, ""),
            note("C", 5, 2, "<chord/>"),
            note("E", 4, 2, ""),
        );
        let score = parse(&doc(&[("Alto", &body)]), 1).unwrap();
        let got: Vec<(i32, f64, f64)> = score.parts[0]
            .notes
            .iter()
            .map(|n| (n.midi, n.start_beat, n.dur_beat))
            .collect();
        assert_eq!(
            got,
            [
                (67, 0.0, 2.0),
                (69, 3.0, 1.0),
                (72, 3.0, 1.0),
                (64, 3.0, 1.0)
            ]
        );
    }

    #[test]
    fn voices_match_by_name_then_position() {
        let body = format!(
            "<measure number=\"1\">{ATTRS}{}</measure>",
            note("C", 4, 2, "")
        );
        let score = parse(
            &doc(&[
                ("Tenor 1", &body),
                ("Organ", &body),
                ("Bass", &body),
                ("x", &body),
                ("y", &body),
            ]),
            1,
        )
        .unwrap();
        let keys: Vec<&str> = score.parts.iter().map(|p| p.voice_key.as_str()).collect();
        assert_eq!(keys, ["T", "A", "B", "B", "P4"]);
    }

    #[test]
    fn lyrics_continue_propagate_and_switch_verse() {
        let lyric = |n: u32, syl: &str, text: &str| {
            format!("<lyric number=\"{n}\"><syllabic>{syl}</syllabic><text>{text}</text></lyric>")
        };
        let sung = format!(
            "<measure number=\"1\">{ATTRS}{}{}{}{}</measure>",
            note(
                "C",
                4,
                2,
                &(lyric(1, "begin", "Ho") + &lyric(2, "begin", "Ha"))
            ),
            note(
                "D",
                4,
                2,
                &(lyric(1, "end", "ly") + &lyric(2, "middle", "gi"))
            ),
            note(
                "E",
                4,
                2,
                &(lyric(1, "single", "God") + &lyric(2, "end", "os"))
            ),
            note("F", 4, 2, &lyric(1, "single", "and")),
        );
        let silent = format!(
            "<measure number=\"1\">{ATTRS}{}{}</measure>",
            note("C", 3, 4, ""),
            note("E", 3, 4, ""),
        );
        let xml = doc(&[("Soprano", &sung), ("Bass", &silent)]);

        let v1 = parse(&xml, 1).unwrap();
        let words = |s: &Score, p: usize| {
            s.parts[p]
                .notes
                .iter()
                .map(|n| n.lyric.clone())
                .collect::<Vec<_>>()
        };
        assert_eq!(v1.max_verse, 2);
        assert_eq!(
            words(&v1, 0),
            ["Ho-", "ly", "God", "and"].map(|s| Some(s.to_string()))
        );
        // The bass borrows at matching onsets only (beats 0 and 2).
        assert_eq!(
            words(&v1, 1),
            [Some("Ho-".to_string()), Some("God".to_string())]
        );

        // Verse 2 covers 3 of 4 syllables: a full verse, so no fallback to verse 1.
        let v2 = parse(&xml, 2).unwrap();
        assert_eq!(
            words(&v2, 0),
            [
                Some("Ha-".to_string()),
                Some("gi-".to_string()),
                Some("os".to_string()),
                None
            ]
        );
    }

    #[test]
    fn sections_need_two_headings() {
        let heading = |t: &str| {
            format!("<direction placement=\"above\"><direction-type><words>{t}</words></direction-type></direction>")
        };
        let m = |n: u32, extra: &str| {
            format!(
                "<measure number=\"{n}\">{ATTRS}{extra}{}</measure>",
                note("C", 4, 2, "")
            )
        };
        let one = parse(&doc(&[("S", &(m(1, &heading("Verse")) + &m(2, "")))]), 1).unwrap();
        assert!(one.sections.is_empty());
        let two = parse(
            &doc(&[(
                "S",
                &(m(1, &heading("Verse")) + &m(2, "") + &m(3, &heading("Refrain"))),
            )]),
            1,
        )
        .unwrap();
        assert_eq!(
            two.sections,
            [
                Section {
                    title: "Verse".into(),
                    measure: 1
                },
                Section {
                    title: "Refrain".into(),
                    measure: 3
                }
            ]
        );
    }

    #[test]
    fn malformed_xml_is_an_error_not_a_panic() {
        assert!(parse("<score-partwise><part>", 1).is_err());
        assert_eq!(parse("<score-partwise/>", 1).unwrap().parts.len(), 0);
    }

    #[test]
    fn engraving_keeps_what_the_page_shows() {
        let attrs = "<attributes><divisions>2</divisions><key><fifths>-1</fifths></key>\
            <time print-object=\"no\"><beats>4</beats><beat-type>4</beat-type></time>\
            <clef><sign>G</sign><line>2</line><clef-octave-change>-1</clef-octave-change></clef></attributes>";
        let eighth = |step: &str, beam: &str, extra: &str| {
            format!("<note><pitch><step>{step}</step><octave>4</octave></pitch><duration>1</duration><type>eighth</type><stem>up</stem><beam number=\"1\">{beam}</beam>{extra}</note>")
        };
        let body = format!(
            "<measure number=\"1\">{attrs}{}{}\
             <note><rest/><duration>1</duration><type>eighth</type></note>\
             <note><pitch><step>B</step><alter>0</alter><octave>4</octave></pitch><duration>3</duration><type>quarter</type><dot/><accidental>natural</accidental><stem>down</stem><tie type=\"start\"/></note>\
             <barline location=\"right\"><bar-style>none</bar-style></barline></measure>\
             <measure number=\"2\"><print new-system=\"yes\"/>\
             <note><pitch><step>B</step><alter>0</alter><octave>4</octave></pitch><duration>4</duration><tie type=\"stop\"/></note>\
             <note><chord/><pitch><step>D</step><octave>5</octave></pitch><duration>4</duration></note></measure>",
            eighth("E", "begin", ""),
            eighth("F", "end", ""),
        );
        let score = parse(&doc(&[("Tenor", &body)]), 1).unwrap();
        let part = &score.parts[0];
        let m1 = &part.staff[0];
        assert_eq!(m1.clef.as_ref().unwrap().octave_change, -1);
        assert_eq!(m1.fifths, Some(-1));
        assert!(!m1.time.as_ref().unwrap().visible);
        assert_eq!(m1.barline, "none");
        assert_eq!((m1.start_beat, m1.end_beat), (0.0, 3.0));
        let kinds: Vec<(&str, u8, usize)> = m1
            .events
            .iter()
            .map(|e| (e.kind.as_str(), e.dots, e.heads.len()))
            .collect();
        assert_eq!(
            kinds,
            [
                ("eighth", 0, 1),
                ("eighth", 0, 1),
                ("eighth", 0, 0),
                ("quarter", 1, 1)
            ]
        );
        assert_eq!(m1.events[0].beams, ["begin"]);
        assert_eq!(m1.events[0].heads[0].pos, 30); // E4
        assert_eq!(m1.events[3].stem_up, Some(false));
        assert_eq!(m1.events[3].heads[0].accidental.as_deref(), Some("natural"));

        let m2 = &part.staff[1];
        assert!(m2.new_system && m2.clef.is_none() && m2.barline == "regular");
        // No <type>: 2 beats is a half note. The tied B and the D form one chord.
        assert_eq!(m2.events.len(), 1);
        assert_eq!(m2.events[0].kind, "half");
        let heads = &m2.events[0].heads;
        assert_eq!(heads.len(), 2);
        // The tied head points at the note it continues; the model has 4 notes.
        assert_eq!(part.notes.len(), 4);
        assert_eq!(heads[0].note, m1.events[3].heads[0].note);
        assert!(heads[0].tie_stop && m1.events[3].heads[0].tie_start);
        assert_eq!(heads[1].note, 3);
    }

    /// The real pieces, when this checkout has them (they are not in git).
    #[test]
    fn local_content_parses() {
        let Ok(dir) = std::fs::read_dir("training-prototype/content") else {
            return;
        };
        for entry in dir
            .flatten()
            .filter(|e| e.path().extension().is_some_and(|x| x == "musicxml"))
        {
            let xml = std::fs::read_to_string(entry.path()).unwrap();
            let score = parse(&xml, 1).unwrap_or_else(|e| panic!("{:?}: {e:?}", entry.path()));
            assert!(!score.parts.is_empty(), "{:?}", entry.path());
            for part in &score.parts {
                assert!(
                    !part.notes.is_empty(),
                    "{:?} {}",
                    entry.path(),
                    part.voice_name
                );
                assert!(part
                    .notes
                    .iter()
                    .all(|n| (20..110).contains(&n.midi) && n.dur_beat > 0.0));
            }
        }
    }
}
