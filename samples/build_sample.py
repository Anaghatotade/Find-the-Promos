"""Builds the PUBLIC demo show: an ORIGINAL fictional microdrama written for this repo
("The Cleaner Was the Heiress"), rendered in the same timestamped screenplay format the
tool reads. It contains no Kuku content and is safe to publish.

  python samples/build_sample.py   ->  samples/the_cleaner_was_the_heiress/*.txt + .zip
"""
import os, zipfile

TITLE = "The Cleaner Was the Heiress"


def fmt(t):
    m, s = divmod(t, 60)
    return f"{int(m):02d}:{s:05.2f}"


def render(n, logline, continuity, beats):
    out, t, scene, blocks, scenes = [], 0.0, 0, [], []
    cur = None
    for b in beats:
        k = b[0]
        if k == "H":
            if cur:
                cur["end"] = t
            scene += 1; cur = {"n": scene, "head": b[1], "start": t, "blocks": []}; scenes.append(cur)
        elif k == "D":
            _, spk, tags, line, cam = b
            dur = round(0.34 * len(line.split()) + 0.8, 1)
            cur["blocks"].append(("CAMERA", t, t + dur + 0.4, cam))
            cur["blocks"].append((f"{spk} ({tags})", t + 0.2, t + 0.2 + dur, f'"{line}"'))
            t = round(t + dur + 0.4, 2)
        elif k == "A":
            _, text, dur, cam = b
            if cam:
                cur["blocks"].append(("CAMERA", t, t + dur, cam))
            cur["blocks"].append(("ACTION", t, t + dur, text))
            t = round(t + dur, 2)
        elif k == "S":
            _, text, dur = b
            cur["blocks"].append(("SOUND FX", t, t + dur, text))
    cur["end"] = t
    out += [f"EPISODE NUMBER: Episode {n}", f"EPISODE LOGLINE: {logline}", f"CONTINUITY NOTES: {continuity}", "",
            "--- SCRIPT START ---", ""]
    for sc in scenes:
        out += [f"SCENE {sc['n']:02d}", f"Scene heading: {sc['head']}", f"Scene start: {fmt(sc['start'])}",
                f"Scene end: {fmt(sc['end'])}", "", "Actions and dialogue:", ""]
        for h, a, z, txt in sc["blocks"]:
            out += [f"**{h}:**", f"Start: ({fmt(a)}) | End: ({fmt(z)})", txt, ""]
    out += ["--- SCRIPT END ---", ""]
    return "\n".join(out)


EPISODES = [
 (1, "At the Halloran Tower gala, night cleaner Mara Quinn watches her fiancé Marcus announce his engagement to the CEO's daughter Sienna, and is humiliated and thrown out, until a stranger stops her at the door.",
  "First episode. Establishes Mara, Marcus, Sienna and Diane Halloran.",
  [("H", "INT. HALLORAN TOWER BALLROOM – NIGHT"),
   ("A", "Mara, in a grey cleaner's uniform, carries a tray of champagne flutes through a glittering crowd.", 3.0, "Wide shot of the chandeliers and the crowd in evening gowns."),
   ("D", "MARCUS", "Charming, Loud", "Thank you all for coming. Tonight I have news.", "Medium shot of Marcus on stage, raising a glass."),
   ("D", "MARA", "Whispering, Hopeful", "He's going to say it. He's finally going to say my name.", "Close-up on Mara's hopeful face."),
   ("D", "MARCUS", "Proud", "Sienna Halloran has agreed to be my wife.", "Close-up on Marcus kissing Sienna's hand."),
   ("A", "The tray slips from Mara's hands and crashes to the marble floor.", 1.6, "Insert of glasses shattering at Mara's feet."),
   ("S", "Glass shattering, then a collective gasp.", 1.5),
   ("D", "MARA", "Shocked, Breaking", "Marcus? You proposed to me last week!", "Close-up on Mara, tears welling."),
   ("D", "SIENNA", "Mocking, Cold", "Proposed? To the girl who mops our floors?", "Medium shot of Sienna descending the stage steps."),
   ("D", "MARCUS", "Cold, Dismissive", "Did you really think I'd marry a cleaner?", "Close-up on Marcus, unbothered."),
   ("A", "Sienna throws her glass of red wine into Mara's face.", 1.5, "Slow-motion close-up as the wine splashes across Mara's face."),
   ("D", "SIENNA", "Venomous", "You were a placeholder. Now get out.", "Two-shot of Sienna towering over Mara."),
   ("D", "DIANE HALLORAN", "Commanding, Icy", "Security. Remove her before she embarrasses this family.", "Low-angle shot of Diane in black velvet."),
   ("D", "MARA", "Trembling, Defiant", "You'll regret this. All of you.", "Close-up on Mara wiping wine from her eyes."),
   ("H", "INT. HALLORAN TOWER LOBBY – CONTINUOUS"),
   ("A", "Two guards drag Mara across the lobby toward the revolving doors.", 2.5, "Tracking shot behind the guards."),
   ("D", "DANIEL OKAFOR", "Calm, Firm", "Let her go. Now.", "Medium shot of a tall man in a dark suit blocking the doors."),
   ("D", "MARA", "Confused, Breathless", "Who are you?", "Close-up on Mara."),
   ("D", "DANIEL OKAFOR", "Grave", "Miss Quinn, your grandfather left you something they never told you about.", "Close-up on Daniel holding a sealed envelope."),
   ("S", "A low ominous string swell.", 2.0)]),
 (2, "The stranger, lawyer Daniel Okafor, tells Mara she is the granddaughter of Halloran founder Edmund Halloran and inherits a controlling stake at midnight, while Diane orders her found first.",
  "Picks up immediately from Episode 1.",
  [("H", "EXT. HALLORAN TOWER STEPS – NIGHT"),
   ("A", "Rain falls on the steps. Daniel opens an umbrella over Mara.", 2.5, "Wide shot of the two of them under the umbrella."),
   ("D", "MARA", "Bitter, Tired", "If this is another joke, I've had enough jokes for one night.", "Close-up on Mara, mascara running."),
   ("D", "DANIEL OKAFOR", "Earnest", "Edmund Halloran was your grandfather. Your mother was his daughter.", "Close-up on Daniel."),
   ("D", "MARA", "Stunned, Whispering", "The man who built this tower? That's impossible.", "Close-up on Mara looking up at the tower."),
   ("D", "DANIEL OKAFOR", "Grave", "He left you fifty-one percent of the company. It becomes yours at midnight, on your birthday.", "Insert of the will's signature page."),
   ("D", "MARA", "Incredulous", "Fifty-one percent? Then Diane Halloran...", "Close-up on Mara."),
   ("D", "DANIEL OKAFOR", "Low, Warning", "Works for you. And she knows it.", "Two-shot under the umbrella."),
   ("H", "INT. DIANE'S PENTHOUSE OFFICE – NIGHT"),
   ("D", "DIANE HALLORAN", "Cold, Furious", "The old man's lawyer is with her. Find the girl before midnight.", "Medium shot of Diane on the phone at the window."),
   ("D", "SECURITY CHIEF (V.O.)", "Flat", "And if she won't come quietly?", "Close-up on the phone."),
   ("D", "DIANE HALLORAN", "Chilling", "Then make sure she never signs anything again.", "Extreme close-up on Diane's eyes."),
   ("H", "EXT. CITY STREET – NIGHT"),
   ("A", "Headlights flood the street. A black car screeches to a stop beside Mara and Daniel.", 2.5, "Low-angle shot of the car."),
   ("S", "Tyres screeching on wet asphalt.", 1.5),
   ("D", "SECURITY CHIEF", "Threatening", "Get in the car, Miss Quinn.", "Close-up on the window rolling down."),
   ("S", "A sharp dramatic sting.", 1.5)]),
 (3, "Daniel refuses to hand Mara over, but a call reveals the original will has been stolen from his office, leaving her claim worthless.",
  "Picks up immediately from Episode 2.",
  [("H", "EXT. CITY STREET – NIGHT"),
   ("D", "DANIEL OKAFOR", "Steely", "She's not going anywhere with you.", "Medium shot of Daniel stepping in front of Mara."),
   ("D", "SECURITY CHIEF", "Menacing", "Mrs. Halloran isn't asking, counselor.", "Close-up on the security chief stepping out."),
   ("D", "MARA", "Defiant, Shaking", "Tell Diane I'm not afraid of her anymore.", "Close-up on Mara, fists clenched."),
   ("D", "SECURITY CHIEF", "Smirking", "You should be.", "Two-shot, the chief inches from Mara."),
   ("A", "A police siren wails nearby. The chief hesitates, then gets back into the car.", 2.5, "Wide shot as the car pulls away."),
   ("S", "Siren fading into the distance.", 2.0),
   ("D", "MARA", "Breathless, Relieved", "It's almost midnight. Then it's over, right?", "Close-up on Mara."),
   ("A", "Daniel's phone buzzes. He listens, his face draining of colour.", 2.5, "Close-up on Daniel's face."),
   ("D", "DANIEL OKAFOR", "Shocked, Quiet", "Someone broke into my office. The original will is gone.", "Close-up on Daniel lowering the phone."),
   ("D", "MARA", "Panicked", "Gone? Then what do I have?", "Close-up on Mara."),
   ("D", "DIANE HALLORAN (V.O.)", "Gloating", "Without the original, you're nobody again.", "Slow push-in on Mara's devastated face."),
   ("S", "Clock tower bells striking midnight.", 2.5)]),
 (4, "Back at work the next morning, Mara is humiliated by Marcus and Sienna in the boardroom, until Daniel walks into the board meeting with a court-certified copy of the will.",
  "The next morning.",
  [("H", "INT. HALLORAN TOWER BOARDROOM – DAY"),
   ("A", "Mara mops the floor of the empty boardroom in her uniform.", 2.5, "Wide shot of the long glass table."),
   ("D", "MARCUS", "Mocking", "Look who came back to clean up her own mess.", "Medium shot of Marcus and Sienna in the doorway."),
   ("A", "Sienna kicks over Mara's bucket. Dirty water floods across the floor.", 1.5, "Insert of the bucket tipping."),
   ("S", "Bucket clattering and water splashing.", 1.5),
   ("D", "SIENNA", "Cruel, Amused", "Oops. Clean it. On your knees.", "Close-up on Sienna smiling."),
   ("D", "MARA", "Calm, Dangerous", "Gladly. Enjoy the room while it's still yours.", "Close-up on Mara, unbroken."),
   ("D", "MARCUS", "Laughing", "Still dreaming, Mara? That's almost sweet.", "Close-up on Marcus."),
   ("A", "Board members file in. Diane takes the chair at the head of the table.", 2.5, "Wide shot of the board seated."),
   ("D", "DIANE HALLORAN", "Triumphant", "Let's make it official. I move to be named chief executive.", "Medium shot of Diane."),
   ("A", "The double doors swing open. Daniel walks in holding a document stamped with a court seal.", 2.5, "Low-angle shot of Daniel in the doorway."),
   ("S", "Heavy doors banging open.", 1.2),
   ("D", "DANIEL OKAFOR", "Authoritative", "Before you vote, the court registered a certified copy of Edmund Halloran's will.", "Close-up on the court seal."),
   ("D", "DIANE HALLORAN", "Stunned", "That's impossible.", "Close-up on Diane, colour draining."),
   ("D", "DANIEL OKAFOR", "Cold, Final", "The majority shareholder is already in the room. She's holding a mop.", "Slow push-in on Mara holding the mop."),
   ("S", "A dramatic orchestral hit.", 1.5)]),
 (5, "Mara takes her seat at the head of the table and fires Marcus, Sienna slaps her, and Diane leaves her with a chilling question about her grandfather's death.",
  "Picks up immediately from Episode 4.",
  [("H", "INT. HALLORAN TOWER BOARDROOM – CONTINUOUS"),
   ("D", "MARCUS", "Shouting, Panicked", "This is a forgery! She's a cleaner!", "Medium shot of Marcus on his feet."),
   ("A", "Mara unties her apron, folds it, and sits in the chair at the head of the table.", 3.0, "Close-up on the apron landing on the glass."),
   ("D", "MARA", "Calm, Commanding", "Marcus, you're fired. Security will help you with your things.", "Close-up on Mara."),
   ("D", "MARCUS", "Desperate", "Mara, please. After everything we had?", "Close-up on Marcus."),
   ("D", "MARA", "Icy", "You told a ballroom I was a placeholder. Consider yourself replaced.", "Two-shot across the table."),
   ("A", "Sienna storms around the table and slaps Mara across the face.", 1.5, "Whip-pan to the slap."),
   ("S", "A sharp slap echoing in the room.", 1.0),
   ("D", "SIENNA", "Screaming, Furious", "You stole my life!", "Close-up on Sienna, shaking."),
   ("D", "MARA", "Steely, Quiet", "That's the last time you touch me.", "Close-up on Mara turning her face back slowly."),
   ("D", "DIANE HALLORAN", "Smiling, Venomous", "Enjoy your chair, Mara.", "Medium shot of Diane rising."),
   ("D", "DIANE HALLORAN", "Chilling", "And ask your lawyer who really killed your grandfather.", "Extreme close-up on Diane's smile."),
   ("D", "MARA", "Shaken", "Killed? He died in his sleep.", "Close-up on Mara turning to Daniel."),
   ("S", "A low cello drone holding into silence.", 2.0)]),
 (6, "Daniel admits Edmund Halloran's death was never investigated, Mara finds a voicemail her grandfather left before he died, and Marcus returns with the stolen original will and a price.",
  "Later that night.",
  [("H", "INT. EDMUND HALLORAN'S STUDY – NIGHT"),
   ("D", "MARA", "Demanding", "Tell me the truth, Daniel. How did my grandfather die?", "Medium shot of Mara among dusty bookshelves."),
   ("D", "DANIEL OKAFOR", "Hesitant, Guilty", "The police called it a heart attack. Nobody asked for an autopsy.", "Close-up on Daniel."),
   ("D", "MARA", "Furious", "Nobody? Or someone made sure nobody did?", "Close-up on Mara."),
   ("A", "Mara opens a desk drawer and finds an old phone with one unheard voicemail.", 3.0, "Insert of the phone screen lighting up."),
   ("D", "EDMUND HALLORAN (V.O.)", "Weak, Urgent", "Mara, if anything happens to me, don't trust anyone in this house. Especially—", "Close-up on Mara listening."),
   ("S", "The voicemail cutting off into static.", 1.5),
   ("D", "MARA", "Whispering, Desperate", "Especially who? Grandpa, who?", "Close-up on Mara's trembling hands."),
   ("A", "The study door creaks open. Marcus stands in the doorway holding a yellowed envelope.", 2.5, "Low-angle shot of Marcus."),
   ("S", "Old door hinges creaking.", 1.2),
   ("D", "MARCUS", "Smug, Threatening", "Looking for this? Edmund's original will.", "Close-up on the envelope."),
   ("D", "MARA", "Shocked", "You stole it?", "Close-up on Mara."),
   ("D", "MARCUS", "Cold, Final", "Want it back? It'll cost you everything.", "Extreme close-up on Marcus's grin."),
   ("S", "A sharp cliffhanger sting into silence.", 1.5)]),
]

if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    d = os.path.join(here, "the_cleaner_was_the_heiress"); os.makedirs(d, exist_ok=True)
    paths = []
    for n, log, cont, beats in EPISODES:
        p = os.path.join(d, f"episode-{n:03d}.txt")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(render(n, log, cont, beats))
        paths.append(p)
    with zipfile.ZipFile(os.path.join(here, "the_cleaner_was_the_heiress.zip"), "w", zipfile.ZIP_DEFLATED) as z:
        for p in paths:
            z.write(p, f"{TITLE}/{os.path.basename(p)}")
    print(f"{len(paths)} episodes -> {d} and the_cleaner_was_the_heiress.zip")
