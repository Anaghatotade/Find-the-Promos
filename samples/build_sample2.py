"""Builds the second PUBLIC demo show: an ORIGINAL fictional mystery thriller written for this repo
("Last Call from the Marigold"), in the same timestamped screenplay format as the first sample.
It contains no Kuku content and is safe to publish.

  python samples/build_sample2.py   ->  samples/last_call_from_the_marigold/*.txt + .zip
"""
import os, zipfile

from build_sample import render

TITLE = "Last Call from the Marigold"
SLUG = "last_call_from_the_marigold"

EPISODES = [
 (1, "On a storm night at Harrow Point harbour, radio operator Nadia Reyes hears a mayday from the Marigold, the fishing boat that sank with her sister Elena three years ago.",
  "First episode. Establishes Nadia, Owen Pike and the loss of the Marigold.",
  [("H", "INT. HARROW POINT HARBOUR RADIO ROOM – NIGHT"),
   ("A", "Rain hammers the window. Nadia logs the weather, alone, a framed photo of a smiling woman on the desk.", 3.0, "Wide shot of the cramped radio room, storm lamps swinging outside."),
   ("D", "NADIA", "Tired, Quiet", "Harrow Point to all vessels. Gale warning in effect. Stay in port.", "Medium shot of Nadia at the microphone."),
   ("S", "Static crackling, then a weak signal breaking through.", 1.5),
   ("D", "RADIO VOICE", "Distorted, Desperate", "Mayday, mayday. This is the Marigold. We are taking on water.", "Insert of the radio dial glowing."),
   ("A", "Nadia freezes. Her pen rolls off the desk.", 1.6, "Close-up on Nadia's face draining of colour."),
   ("D", "NADIA", "Shaking, Disbelieving", "The Marigold sank three years ago.", "Close-up on the framed photo of Elena on the boat's deck."),
   ("D", "RADIO VOICE", "Distorted, Pleading", "Nadia, it's me. Please. Don't let them find me.", "Extreme close-up on the speaker grille."),
   ("D", "NADIA", "Breaking, Desperate", "Elena? Elena, where are you?", "Close-up on Nadia gripping the microphone."),
   ("S", "The signal dissolving into static.", 1.5),
   ("H", "INT. RADIO ROOM – MOMENTS LATER"),
   ("A", "The door bangs open. Owen Pike, the harbour master, shakes rain off his coat.", 2.5, "Medium shot of Owen in the doorway."),
   ("D", "OWEN PIKE", "Gruff, Wary", "I heard the alarm from the dock. What was that?", "Two-shot of Owen and Nadia."),
   ("D", "NADIA", "Urgent", "A mayday from the Marigold. It was her voice, Owen. It was Elena.", "Close-up on Nadia."),
   ("D", "OWEN PIKE", "Flat, Careful", "That's not possible. Someone is playing a sick joke on you.", "Close-up on Owen avoiding her eyes."),
   ("D", "NADIA", "Firm", "Then explain why the Marigold's beacon is transmitting right now.", "Insert of a blinking dot on the tracking screen."),
   ("D", "OWEN PIKE", "Quiet, Shaken", "Because I took that beacon off the wreck myself. And I smashed it.", "Extreme close-up on Owen's face."),
   ("S", "A deep foghorn sounding across the bay.", 2.0)]),
 (2, "Nadia confronts Owen about the beacon and goes to Sheriff Brannigan, who insists the case is closed, until she finds something of Elena's that should be at the bottom of the sea.",
  "Picks up the next morning.",
  [("H", "EXT. HARROW POINT DOCK – DAWN"),
   ("D", "NADIA", "Angry, Accusing", "Why would you take the beacon off a dead woman's boat?", "Close-up on Nadia blocking Owen's path."),
   ("D", "OWEN PIKE", "Defensive, Tense", "Because the insurance men wanted it, and I needed the money. That's all.", "Medium shot of Owen coiling rope."),
   ("D", "NADIA", "Cold", "You told me you never dived on the wreck.", "Close-up on Nadia."),
   ("A", "Owen drops the rope and walks away without answering.", 2.0, "Wide shot of the empty dock in grey light."),
   ("H", "INT. SHERIFF'S OFFICE – DAY"),
   ("D", "SHERIFF BRANNIGAN", "Patient, Patronising", "Grief does strange things, Nadia. Storms do strange things to radios.", "Medium shot of the sheriff behind his desk."),
   ("D", "NADIA", "Pleading", "She said my name. She said don't let them find me.", "Close-up on Nadia."),
   ("D", "SHERIFF BRANNIGAN", "Firm, Final", "The case is closed. I signed the report myself.", "Close-up on the sheriff closing a thin folder."),
   ("H", "INT. HARBOUR OFFICE – DAY"),
   ("A", "Nadia returns to the office. On the coat hook hangs a yellow rain jacket, bone dry.", 3.0, "Slow push-in on the yellow jacket."),
   ("D", "NADIA", "Whispering, Stunned", "That's Elena's jacket. She was wearing it the night she drowned.", "Close-up on Nadia's trembling hand touching the sleeve."),
   ("A", "A folded note falls from the pocket.", 1.5, "Insert of the note landing on the floor."),
   ("D", "NADIA", "Reading, Afraid", "Don't trust the sheriff. He was there.", "Extreme close-up on the handwriting."),
   ("S", "The radio behind her crackling back to life.", 1.5)]),
 (3, "Nadia takes a boat out to the wreck site and discovers the Marigold's lifeboat is missing, then a phone call brings a voice she never expected.",
  "Later the same day. Owen reluctantly helps.",
  [("H", "EXT. OPEN WATER ABOVE THE WRECK – DAY"),
   ("D", "OWEN PIKE", "Low, Uneasy", "We shouldn't be out here. People are watching the harbour.", "Medium shot of Owen at the tiller."),
   ("D", "NADIA", "Steady", "Then they already know. Take me down to her.", "Close-up on Nadia pulling on a dive mask."),
   ("A", "Underwater, Nadia swims along the broken hull of the Marigold.", 3.5, "Wide underwater shot of the wreck in green light."),
   ("A", "The lifeboat cradle is empty. Its ropes have been cut clean.", 2.5, "Close-up on the cut ropes swaying."),
   ("H", "EXT. BOAT – CONTINUOUS"),
   ("D", "NADIA", "Breathless, Certain", "The lifeboat is gone. The ropes were cut, Owen. Someone got off that boat.", "Close-up on Nadia surfacing."),
   ("D", "OWEN PIKE", "Pale, Quiet", "The report said all hands were lost.", "Close-up on Owen."),
   ("D", "NADIA", "Sharp", "The report the sheriff wrote.", "Two-shot as the boat rocks."),
   ("H", "INT. NADIA'S COTTAGE – NIGHT"),
   ("A", "Nadia's phone buzzes. Unknown number. She answers. Only breathing.", 3.0, "Close-up on the phone screen."),
   ("D", "NADIA", "Cautious", "Who is this?", "Close-up on Nadia."),
   ("D", "LITTLE GIRL (PHONE)", "Small, Scared", "Aunt Nadia? Mum says you have to stop looking.", "Extreme close-up on Nadia's face."),
   ("D", "NADIA", "Stunned, Whispering", "Mum? Elena doesn't have a daughter.", "Close-up on Nadia lowering the phone."),
   ("S", "The line going dead.", 1.5)]),
 (4, "Ferry owner Mrs Calloway reveals who profited from the sinking, and Nadia overhears the sheriff and Owen arguing about the night the Marigold went down.",
  "The next day. Nadia now suspects both men.",
  [("H", "INT. CALLOWAY FERRY OFFICE – DAY"),
   ("D", "MRS CALLOWAY", "Dry, Knowing", "Three hundred thousand. That's what the Marigold's insurance paid out.", "Medium shot of Mrs Calloway pouring tea."),
   ("D", "NADIA", "Surprised", "Elena's policy went to me. I never saw a penny.", "Close-up on Nadia."),
   ("D", "MRS CALLOWAY", "Quiet, Pointed", "It didn't go to you, love. It went to the man who co-signed the boat loan.", "Close-up on a folded bank statement slid across the table."),
   ("A", "Nadia unfolds it. One name is circled in red.", 2.0, "Insert of the circled name: T. Brannigan."),
   ("H", "EXT. BEHIND THE BOATHOUSE – NIGHT"),
   ("A", "Nadia crouches in the dark as two figures argue by the slipway.", 2.5, "Wide shot through wet reeds."),
   ("D", "SHERIFF BRANNIGAN", "Hissing, Furious", "You were supposed to sink that beacon with her.", "Medium shot of the sheriff jabbing a finger at Owen."),
   ("D", "OWEN PIKE", "Desperate", "She was alive when we left her, Tom. I heard her calling.", "Close-up on Owen."),
   ("D", "SHERIFF BRANNIGAN", "Cold", "Then whoever's on that radio had better stay quiet.", "Close-up on the sheriff."),
   ("A", "A branch snaps under Nadia's boot. Both men turn.", 1.6, "Close-up on Nadia's foot on the branch."),
   ("S", "A twig snapping, loud in the silence.", 1.0),
   ("D", "OWEN PIKE", "Grim, Regretful", "You should have let her stay dead, Nadia.", "Low-angle shot of Owen stepping into the light."),
   ("S", "A low ominous drone.", 2.0)]),
 (5, "Nadia escapes to the old lighthouse, where the radio signal is coming from, and finally comes face to face with the truth about her sister.",
  "Continues directly from Episode 4. Final episode of the arc.",
  [("H", "INT. HARROW POINT LIGHTHOUSE – NIGHT"),
   ("A", "Nadia climbs the spiral stairs, torch shaking. A radio set glows at the top.", 3.0, "Low-angle shot up the spiral stairwell."),
   ("D", "NADIA", "Breathless, Calling", "Elena? I know you're here. I heard you.", "Close-up on Nadia reaching the top step."),
   ("A", "A woman steps out from behind the lamp housing. Thin, older, unmistakable.", 2.5, "Slow reveal as the beam sweeps across her face."),
   ("D", "ELENA", "Tearful, Quiet", "Hello, little sister.", "Close-up on Elena."),
   ("D", "NADIA", "Breaking", "Three years. I buried an empty coffin for you.", "Close-up on Nadia, tears running."),
   ("D", "ELENA", "Urgent, Low", "I didn't drown. I hid. They sank my boat to collect the money, and they left me in the water.", "Two-shot in the sweeping light."),
   ("D", "NADIA", "Furious", "Brannigan and Owen.", "Close-up on Nadia."),
   ("D", "ELENA", "Afraid", "And now they know that you know.", "Close-up on Elena looking down the stairwell."),
   ("S", "Footsteps climbing the iron stairs below.", 2.0),
   ("D", "SHERIFF BRANNIGAN (O.S.)", "Calm, Menacing", "Evening, ladies. Nobody needs to get hurt tonight.", "Low-angle shot of a torch beam rising."),
   ("A", "The lighthouse lamp shuts off. Total darkness.", 2.0, "Wide shot as the beam dies over the bay."),
   ("D", "ELENA", "Whispering", "Nadia. Don't let go of my hand.", "Black screen."),
   ("S", "A single gunshot echoing over the water.", 2.0)]),
]

if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    d = os.path.join(here, SLUG); os.makedirs(d, exist_ok=True)
    paths = []
    for n, log, cont, beats in EPISODES:
        p = os.path.join(d, f"episode-{n:03d}.txt")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(render(n, log, cont, beats))
        paths.append(p)
    with zipfile.ZipFile(os.path.join(here, f"{SLUG}.zip"), "w", zipfile.ZIP_DEFLATED) as z:
        for p in paths:
            z.write(p, f"{TITLE}/{os.path.basename(p)}")
    print(f"{len(paths)} episodes -> {d} and {SLUG}.zip")
