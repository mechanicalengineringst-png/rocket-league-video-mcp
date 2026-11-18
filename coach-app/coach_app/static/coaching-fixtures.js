/**
 * Replay Lab — Tactical Coaching Fixtures & Episode Adapter
 *
 * Implements Stage1EpisodePacketV0 / EpisodeEvidenceV0 compliant multi-node
 * tactical episodes for the interactive AI coaching experience.
 *
 * Each episode contains:
 * - 2 to 4 decision nodes (N1 -> N2 -> N3) with time cutoffs (t0)
 * - Explicit relations and delta metrics between nodes (Delta t, Delta boost, Delta distance)
 * - Structured evidence items with epistemic categories:
 *     OBSERVED | DERIVED | HYPOTHETICAL | UNKNOWN | RETROSPECTIVE
 * - Pre-decision alternatives with feasibility ratings and trade-offs
 * - Contributing earlier decisions (H.1, H.2 causal hypotheses)
 * - Quarantined Stage 2 retrospective outcome (quarantined behind temporal firewall)
 */

(function (global) {
  'use strict';

  const COACHING_FIXTURES = [
    {
      schema: 'EpisodeEvidenceV0',
      episode_id: 'ep-midfield-challenge-01',
      title: 'First-Man Diving Challenge vs Shadow Transition',
      subtitle: '2v2 Midfield Transition · Blue Team Defence',
      player_id: 'p-blue-focus',
      player_name: 'Blue Defender (You)',
      focus_slot: 'focus',
      slots: {
        focus: { team: 'blue', name: 'You (1st Man)' },
        teammate: { team: 'blue', name: 'Teammate (2nd Man)' },
        opponent_1: { team: 'orange', name: 'Orange Attacker (Ball Carrier)' },
        opponent_2: { team: 'orange', name: 'Orange Support' }
      },
      window: {
        start_s: 1.0,
        end_s: 9.5,
        length_s: 8.5,
        stage1_horizon_s: 6.0
      },
      // 3 sequential decision moments leading to the critical moment
      nodes: [
        {
          node_id: 'N1',
          label: 'Midfield Boost Pickup & Forward Push',
          t0: 2.0,
          is_primary: false,
          information_cutoff_s: 2.0,
          summary: 'Accelerating toward midfield corner boost while ball bounces near midfield.',
          car_state: {
            position: [-1200, -800, 17],
            velocity: [450, 1100, 0],
            speed_uups: 1188,
            boost: 82,
            forward: [0.38, 0.92, 0]
          },
          ball_state: {
            position: [600, 400, 140],
            velocity: [120, 240, 50],
            speed_uups: 272
          },
          teammate_state: {
            position: [-1800, -2800, 17],
            velocity: [100, 400, 0],
            boost: 45,
            distance_to_focus: 2088
          },
          opponent_state: {
            position: [800, 800, 17],
            velocity: [-200, -500, 0],
            boost: 70,
            distance_to_ball: 447
          },
          coaching: {
            headline: 'Upfield commitment without confirmed possession',
            stance: 'neutral',
            confidence: 'hypothesis',
            takeaway: 'Collecting midfield boost is viable, but recognize that pushing beyond the halfway line commits you as first man.'
          }
        },
        {
          node_id: 'N2',
          label: 'Opponent Possession Read & Closing Approach',
          t0: 4.0,
          is_primary: false,
          information_cutoff_s: 4.0,
          summary: 'Opponent secures clean bounce dribble; focus car continues advancing forward rather than angling into shadow defense.',
          car_state: {
            position: [-400, 300, 17],
            velocity: [300, 1400, 0],
            speed_uups: 1431,
            boost: 54,
            forward: [0.21, 0.98, 0]
          },
          ball_state: {
            position: [350, 950, 210],
            velocity: [-80, -320, 80],
            speed_uups: 339
          },
          teammate_state: {
            position: [-1400, -1900, 17],
            velocity: [300, 600, 0],
            boost: 38,
            distance_to_focus: 2416
          },
          opponent_state: {
            position: [280, 1150, 17],
            velocity: [-120, -580, 0],
            boost: 65,
            distance_to_ball: 215
          },
          coaching: {
            headline: 'Forward momentum maintained despite opponent having controlled possession',
            stance: 'concern',
            confidence: 'hypothesis',
            takeaway: 'When the opponent clearly controls the bounce dribble, continuing forward straightens your attack angle and eliminates shadow positioning.'
          }
        },
        {
          node_id: 'N3',
          label: 'Dive Challenge Commitment vs Shadow Transition',
          t0: 5.8,
          is_primary: true,
          information_cutoff_s: 5.8,
          summary: 'Critical decision point: Focus player commits to an aggressive dive challenge while opponent still has flip available and teammate is not yet in net.',
          car_state: {
            position: [120, 1100, 25],
            velocity: [200, 1650, 180],
            speed_uups: 1671,
            boost: 24,
            forward: [0.12, 0.99, 0.11]
          },
          ball_state: {
            position: [180, 1420, 290],
            velocity: [-50, -620, 120],
            speed_uups: 633
          },
          teammate_state: {
            position: [-600, -1100, 17],
            velocity: [150, 950, 0],
            boost: 34,
            distance_to_focus: 2315
          },
          opponent_state: {
            position: [160, 1540, 17],
            velocity: [-40, -780, 0],
            boost: 58,
            distance_to_ball: 121
          },
          coaching: {
            headline: 'Over-aggressive first-man challenge with trailing teammate in rotation',
            stance: 'concern',
            confidence: 'hypothesis',
            agreement: 'agree',
            assessment: 'High-risk commitment. Opponent has ball under close control with bounce height suitable for a flick, while your teammate is 2,300 units behind and still rotating back towards goal.',
            feasible_alternatives: [
              {
                id: 'alt-shadow',
                action: 'Shadow defensively towards back post',
                feasibility: 'feasible',
                feasibility_label: 'Fully Feasible',
                risk_level: 'low',
                pros: 'Allows teammate 1.6s to reach defensive back-post; forces opponent into low-angle early shot or flick from midfield.',
                cons: 'Surrenders midfield possession territory.',
                description: 'Turn car car-cam right towards own right corner, match ball speed, and prepare to turn into the shot trajectory once teammate establishes net cover.'
              },
              {
                id: 'alt-fake-challenge',
                action: 'Drive fake challenge and immediate rotation',
                feasibility: 'feasible',
                feasibility_label: 'Feasible with timing',
                risk_level: 'medium',
                pros: 'Forces opponent to trigger their flick or touch early while you maintain recovery momentum away from the ball.',
                cons: 'If opponent ignores the fake, they retain midfield control with space.',
                description: 'Tap supersonic approach, turn sharp left away from ball at 800 uu distance, baiting opponent flick.'
              },
              {
                id: 'alt-aerial-dive',
                action: 'Direct diving challenge into ball (Chosen action)',
                feasibility: 'constrained',
                feasibility_label: 'Severely Constrained',
                risk_level: 'high',
                pros: 'If successful, results in immediate midfield turnover.',
                cons: 'Whiff or flick over results in full defensive elimination; recovery takes >2.8s; leaves teammate in a 2v1.',
                description: 'Flips forward into 50/50 block. Highly vulnerable to opponent delay or high pop.'
              }
            ],
            observed_evidence: [
              {
                id: 'E.focus.boost',
                kind: 'observation',
                label: 'Focus Boost at t0',
                value: '24 / 100',
                unit: 'boost',
                provenance: 'replay_sample',
                description: 'Car has only 24 boost remaining, preventing sustained aerial recovery or speed adjustments after jump.'
              },
              {
                id: 'E.focus.speed',
                kind: 'observation',
                label: 'Focus Approach Speed',
                value: '1671 uu/s (80% max)',
                unit: 'uu/s',
                provenance: 'replay_sample',
                description: 'Approaching with high forward momentum, making a sharp defensive turn impossible without braking.'
              },
              {
                id: 'E.opponent.possession',
                kind: 'derived',
                label: 'Opponent Possession Distance',
                value: '121 uu (Tight control)',
                unit: 'uu',
                provenance: 'derived_spatial',
                description: 'Opponent is directly underneath the ball with car nose aligned towards blue goal.'
              },
              {
                id: 'E.teammate.spacing',
                kind: 'observation',
                label: 'Teammate Separation Distance',
                value: '2315 uu',
                unit: 'uu',
                provenance: 'replay_sample',
                description: 'Teammate is midfield-defensive, 2300 units behind play and travelling at 950 uu/s.'
              },
              {
                id: 'E.teammate.cover_time',
                kind: 'derived',
                label: 'Estimated Teammate Cover Time',
                value: '2.1 seconds to goal line',
                unit: 'seconds',
                provenance: 'derived_kinematic',
                description: 'Teammate cannot reach blue goal line before an unhindered opponent shot from this distance.'
              },
              {
                id: 'E.ball.trajectory',
                kind: 'observation',
                label: 'Ball Height and Upward Arc',
                value: 'Z = 290 uu, Vz = +120 uu/s',
                unit: 'uu',
                provenance: 'replay_sample',
                description: 'Ball is in ascending phase off ground bounce, placing it in prime position for an opponent 45-degree or front flick.'
              }
            ],
            earlier_contributors: [
              {
                id: 'H.1',
                earlier_node: 'N1',
                concerns_node: 'N3',
                question: 'Focus player used 28 boost at N1 pushing upfield rather than pathing over small pads. Did this boost deficit constrain defensive options at N3?',
                evidence_refs: ['D.N1-N2.boost', 'N1/E.focus.boost', 'N3/E.focus.boost'],
                status: 'hypothesis_unverified',
                not_established: 'Whether higher boost would have saved the play; however, low boost eliminated high-aerial challenge options.'
              },
              {
                id: 'H.2',
                earlier_node: 'N2',
                concerns_node: 'N3',
                question: 'At N2, focus player maintained a straight attack angle instead of peeling wide for shadow defense. Did this eliminate turning radius for shadowing at N3?',
                evidence_refs: ['D.N2-N3.forward_angle', 'N2/E.focus.forward'],
                status: 'hypothesis_unverified',
                not_established: 'Whether opponent would have flicked earlier if shadowed; no definitive causal claim is made.'
              }
            ],
            takeaway: 'In 2v2 as first man when opponent has controlled bounce dribble, your job is not to win the ball cleanly—it is to buy 1.5–2.0 seconds for your second man to establish back-post defense. Prioritize shadowing or fake-challenging over diving.',
            unknowns: [
              'What each player saw on screen (camera POV, ball cam status). Replays record coordinates, not player perception.',
              'Controller analog stick input and exact jump timing intentions.',
              'Voice comms or quick chat between Blue teammates.',
              'Opponent mechanical confidence (flick accuracy).'
            ]
          }
        }
      ],
      relations: [
        { from: 'N1', to: 'N2', delta_t_s: 2.0, delta_label: '2.0s transition' },
        { from: 'N2', to: 'N3', delta_t_s: 1.8, delta_label: '1.8s commitment' }
      ],
      changes: [
        {
          id: 'D.N1-N2.boost',
          from_node: 'N1',
          to_node: 'N2',
          field: 'focus.boost',
          from_val: 82,
          to_val: 54,
          delta: -28,
          label: 'Boost spent during upfield sprint: -28'
        },
        {
          id: 'D.N2-N3.team_spacing',
          from_node: 'N2',
          to_node: 'N3',
          field: 'teammate.distance',
          from_val: 2416,
          to_val: 2315,
          delta: -101,
          label: 'Teammate spacing remained >2300 units; second man unable to close gap'
        },
        {
          id: 'D.N2-N3.forward_angle',
          from_node: 'N2',
          to_node: 'N3',
          field: 'focus.alignment',
          from_val: 'Forward approach',
          to_val: 'Direct nose-dive',
          delta: 0,
          label: 'Car alignment locked into direct forward trajectory'
        }
      ],
      timeline_events: [
        { id: 'T.boost_pickups.1', t: 1.8, type: 'boost_pickup', label: 'Blue Focus grabbed 100-pad at midfield right' },
        { id: 'T.touch.1', t: 3.6, type: 'touch', label: 'Orange Attacker touched ball (bounce dribble setup)' },
        { id: 'T.touch.2', t: 6.1, type: 'touch', label: 'Orange Attacker flicked ball over diving defender' }
      ],
      // Quarantined Retrospective (Stage 2) — Protected by UI firewall
      retrospective: {
        stage: 2,
        warning: 'HINDSIGHT INFORMATION: Observed after t0 (5.8s). This information was NOT available to the player at decision time and must NEVER be used to evaluate decision quality.',
        summary: 'Orange Attacker executed a forward 45-degree flick at t=6.1s. Focus player jumped into a diving challenge at t=5.9s, was beaten cleanly in the air, and landed upside down at t=7.2s. Orange scored at t=8.4s.',
        events: [
          { t: 5.9, label: 'Focus player committed jump and dodge forward' },
          { t: 6.1, label: 'Opponent touched ball (elevating it to Z=580 uu over defender)' },
          { t: 6.8, label: 'Teammate attempted emergency goal-line save from awkward angle' },
          { t: 8.4, label: 'Orange team scored goal (Outcome)' }
        ],
        consequence: 'Diving challenge left teammate in an unprotectable 2v1 situation, resulting in a conceded goal.'
      }
    },

    {
      schema: 'EpisodeEvidenceV0',
      episode_id: 'ep-lastman-defense-02',
      title: 'Last-Man Goal-Line Defense & Over-Commitment',
      subtitle: '2v2 Goal-Line Stand · Orange Team Offense',
      player_id: 'p-blue-focus',
      player_name: 'Blue Last Man (You)',
      focus_slot: 'focus',
      slots: {
        focus: { team: 'blue', name: 'You (Last Man)' },
        teammate: { team: 'blue', name: 'Teammate (Recovering)' },
        opponent_1: { team: 'orange', name: 'Orange Shooter' },
        opponent_2: { team: 'orange', name: 'Orange Demolition Runner' }
      },
      window: {
        start_s: 13.0,
        end_s: 21.0,
        length_s: 8.0,
        stage1_horizon_s: 18.0
      },
      nodes: [
        {
          node_id: 'N1',
          label: 'Back-Post Rotation & Net Coverage',
          t0: 14.2,
          is_primary: false,
          information_cutoff_s: 14.2,
          summary: 'Properly entered own goal area via back post with car angled towards midfield.',
          car_state: {
            position: [-500, -5050, 17],
            velocity: [600, 100, 0],
            speed_uups: 608,
            boost: 52,
            forward: [0.98, 0.18, 0]
          },
          ball_state: {
            position: [2400, -2200, 450],
            velocity: [-400, -900, -100],
            speed_uups: 989
          },
          teammate_state: {
            position: [1200, 100, 17],
            velocity: [-500, -1100, 0],
            boost: 12,
            distance_to_focus: 5434
          },
          opponent_state: {
            position: [1900, -2500, 17],
            velocity: [-300, -800, 0],
            boost: 65,
            distance_to_ball: 608
          },
          coaching: {
            headline: 'Sound back-post positioning established',
            stance: 'support',
            confidence: 'hypothesis',
            takeaway: 'Back-post entry gives you full vision of the net, both goalposts, and incoming attacker routes.'
          }
        },
        {
          node_id: 'N2',
          label: 'Forward Creep Off Goal Line',
          t0: 16.0,
          is_primary: false,
          information_cutoff_s: 16.0,
          summary: 'Instead of holding back-post line until attacker commits, defender creeps 850 units forward towards front post.',
          car_state: {
            position: [250, -4200, 17],
            velocity: [200, 800, 0],
            speed_uups: 824,
            boost: 46,
            forward: [0.24, 0.97, 0]
          },
          ball_state: {
            position: [1200, -3200, 280],
            velocity: [-550, -750, 200],
            speed_uups: 951
          },
          teammate_state: {
            position: [800, -1800, 17],
            velocity: [-200, -1300, 0],
            boost: 24,
            distance_to_focus: 2462
          },
          opponent_state: {
            position: [950, -3450, 17],
            velocity: [-400, -700, 0],
            boost: 40,
            distance_to_ball: 350
          },
          coaching: {
            headline: 'Creeping off the goal line narrows your defensive coverage angle',
            stance: 'concern',
            confidence: 'hypothesis',
            takeaway: 'Creeping forward while last man removes your ability to defend high backboard rebounds or far-post hook shots.'
          }
        },
        {
          node_id: 'N3',
          label: 'Awkward Backwards Aerial vs Goal-Line Hold',
          t0: 17.5,
          is_primary: true,
          information_cutoff_s: 17.5,
          summary: 'Ball is popped high towards own crossbar; defender is caught under the ball with zero backwards momentum.',
          car_state: {
            position: [100, -4400, 17],
            velocity: [50, -100, 0],
            speed_uups: 111,
            boost: 38,
            forward: [0.1, 0.99, 0]
          },
          ball_state: {
            position: [0, -4800, 680],
            velocity: [-100, -400, -150],
            speed_uups: 438
          },
          teammate_state: {
            position: [400, -3100, 17],
            velocity: [-100, -1100, 0],
            boost: 30,
            distance_to_focus: 1334
          },
          opponent_state: {
            position: [600, -3800, 17],
            velocity: [-500, -900, 0],
            boost: 30,
            distance_to_ball: 1253
          },
          coaching: {
            headline: 'Defensive dilemma caused by premature forward creep at N2',
            stance: 'concern',
            confidence: 'hypothesis',
            agreement: 'agree',
            assessment: 'Caught flat-footed inside own crease under high crossbar flight. Because the car crept out at N2, the ball is now directly above and slightly behind your roof.',
            feasible_alternatives: [
              {
                id: 'alt-hold-backpost',
                action: 'Remain patient on back-post goal line (Alternative from N2)',
                feasibility: 'feasible',
                feasibility_label: 'Fully Feasible',
                risk_level: 'low',
                pros: 'Maintains forward-driving momentum toward any shot; natural jump trajectory toward crossbar.',
                cons: 'Requires trust that teammate can contest near-post roll.',
                description: 'Hold wheels grounded on back-post line; drive forward into save instead of jumping backwards.'
              },
              {
                id: 'alt-backboard-drive',
                action: 'Drive up backboard for backboard clear',
                feasibility: 'constrained',
                feasibility_label: 'Timing Constrained',
                risk_level: 'medium',
                pros: 'Intercepts high ball before bounce.',
                cons: 'Requires 1.2s lead time; difficult from stopped creep position.',
                description: 'Drive up the curve behind goal and aerial downward into midfield.'
              }
            ],
            observed_evidence: [
              {
                id: 'E.focus.position_y',
                kind: 'observation',
                label: 'Focus Distance from Goal Line',
                value: '720 uu forward of goal line',
                unit: 'uu',
                provenance: 'replay_sample',
                description: 'Car has drifted into the crease rather than defending from the line.'
              },
              {
                id: 'E.ball.height',
                kind: 'observation',
                label: 'Ball Height and Angle',
                value: 'Z = 680 uu (Above crossbar)',
                unit: 'uu',
                provenance: 'replay_sample',
                description: 'Ball trajectory loops directly above the net opening.'
              },
              {
                id: 'E.focus.velocity_y',
                kind: 'observation',
                label: 'Focus Forward Velocity',
                value: '-100 uu/s (Essentially stationary)',
                unit: 'uu/s',
                provenance: 'replay_sample',
                description: 'Car has lost all kinetic energy; jumping from standstill requires pure vertical boost expenditure.'
              }
            ],
            earlier_contributors: [
              {
                id: 'H.1',
                earlier_node: 'N2',
                concerns_node: 'N3',
                question: 'At N2, focus player moved forward 850 units off back-post. Did leaving the back-post line directly cause the awkward jump angle at N3?',
                evidence_refs: ['D.N1-N2.creep_distance', 'N2/E.focus.position'],
                status: 'hypothesis_unverified',
                not_established: 'Whether holding back post would have guaranteed a clean clear, but physics confirms jump angle would have been forward rather than backwards.'
              }
            ],
            takeaway: 'As last man defending high balls, never creep past your back post until the attacker actually makes ball contact. Forward momentum into the save is 10x easier than backwards aerials.',
            unknowns: [
              'Whether focus car had a dodge flip still available at t0.',
              'Exact camera pitch angle and whether player could see the crossbar in relation to the ball.'
            ]
          }
        }
      ],
      relations: [
        { from: 'N1', to: 'N2', delta_t_s: 1.8, delta_label: '1.8s positioning' },
        { from: 'N2', to: 'N3', delta_t_s: 1.5, delta_label: '1.5s creep & lock' }
      ],
      changes: [
        {
          id: 'D.N1-N2.creep_distance',
          from_node: 'N1',
          to_node: 'N2',
          field: 'focus.goal_line_offset',
          from_val: 'Back-post line',
          to_val: '+850 uu crease',
          delta: 850,
          label: 'Defender left goal-line safety: +850 uu into crease'
        }
      ],
      timeline_events: [
        { id: 'T.touch.10', t: 15.8, type: 'touch', label: 'Orange attacker chipped ball toward crossbar' },
        { id: 'T.bump.1', t: 16.9, type: 'bump', label: 'Orange runner attempted demo on recovering Blue teammate' }
      ],
      retrospective: {
        stage: 2,
        warning: 'HINDSIGHT INFORMATION: Observed after t0 (17.5s). Quarantined by temporal firewall.',
        summary: 'Defender attempted a backwards vertical jump at t=17.7s, grazed the ball with car undercarriage, but could not redirect it away. Ball bounced off backboard and Orange scored at t=19.4s.',
        events: [
          { t: 17.7, label: 'Defender jumped backwards from stationary pose' },
          { t: 18.2, label: 'Weak undercarriage contact (12 km/h deflection)' },
          { t: 19.4, label: 'Orange team goal' }
        ],
        consequence: 'Conceded goal from awkward defensive geometry.'
      }
    },

    {
      schema: 'EpisodeEvidenceV0',
      episode_id: 'ep-counterattack-shot-03',
      title: 'Midfield Loose Ball Transition & Shot Selection',
      subtitle: '2v2 Offensive Counter · Transition Play',
      player_id: 'p-blue-focus',
      player_name: 'Blue Attacker (You)',
      focus_slot: 'focus',
      slots: {
        focus: { team: 'blue', name: 'You (Counter-Attacker)' },
        teammate: { team: 'blue', name: 'Teammate (Supporting Midfield)' },
        opponent_1: { team: 'orange', name: 'Orange Goalkeeper' },
        opponent_2: { team: 'orange', name: 'Orange Demolished / Recovering' }
      },
      window: {
        start_s: 27.0,
        end_s: 35.0,
        length_s: 8.0,
        stage1_horizon_s: 32.0
      },
      nodes: [
        {
          node_id: 'N1',
          label: 'Loose Ball Recovery at Midfield',
          t0: 28.0,
          is_primary: false,
          information_cutoff_s: 28.0,
          summary: 'Teammate cleared ball to midfield; focus car secures possession with 78 boost.',
          car_state: {
            position: [200, 200, 17],
            velocity: [100, 1100, 0],
            speed_uups: 1104,
            boost: 78,
            forward: [0.09, 0.99, 0]
          },
          ball_state: {
            position: [300, 800, 120],
            velocity: [50, 400, 0],
            speed_uups: 403
          },
          teammate_state: {
            position: [-1100, -1200, 17],
            velocity: [400, 500, 0],
            boost: 50,
            distance_to_focus: 1910
          },
          opponent_state: {
            position: [0, 4800, 17],
            velocity: [0, 0, 0],
            boost: 90,
            distance_to_ball: 4011
          },
          coaching: {
            headline: 'Clean possession secured with numerical advantage',
            stance: 'support',
            confidence: 'hypothesis',
            takeaway: 'Opponent 2 is out of play; you have a temporary 2v1 advantage against the sole orange defender in net.'
          }
        },
        {
          node_id: 'N2',
          label: 'Approach Angle & Ball Control Choice',
          t0: 29.5,
          is_primary: false,
          information_cutoff_s: 29.5,
          summary: 'Opportunity to catch ball on car roof for flick or bounce dribble vs slamming an immediate direct boom.',
          car_state: {
            position: [250, 1900, 17],
            velocity: [50, 1500, 0],
            speed_uups: 1500,
            boost: 62,
            forward: [0.03, 0.99, 0]
          },
          ball_state: {
            position: [270, 2300, 95],
            velocity: [20, 600, 0],
            speed_uups: 600
          },
          teammate_state: {
            position: [-800, 300, 17],
            velocity: [200, 1000, 0],
            boost: 45,
            distance_to_focus: 1914
          },
          opponent_state: {
            position: [-200, 4900, 17],
            velocity: [100, 200, 0],
            boost: 85,
            distance_to_ball: 2646
          },
          coaching: {
            headline: 'High-speed approach limits ball control options',
            stance: 'neutral',
            confidence: 'hypothesis',
            takeaway: 'Maintaining supersonic speed directly into the rolling ball forces a direct strike rather than giving time for a controlled carry.'
          }
        },
        {
          node_id: 'N3',
          label: 'Shot Selection: Direct Boomer vs Controlled Cut',
          t0: 31.0,
          is_primary: true,
          information_cutoff_s: 31.0,
          summary: 'Attacker takes a direct high-speed shot straight at the established goalkeeper instead of cutting around or passing.',
          car_state: {
            position: [280, 3100, 17],
            velocity: [40, 1800, 0],
            speed_uups: 1800,
            boost: 44,
            forward: [0.02, 0.99, 0]
          },
          ball_state: {
            position: [290, 3400, 110],
            velocity: [10, 800, 0],
            speed_uups: 800
          },
          teammate_state: {
            position: [-600, 1800, 17],
            velocity: [150, 1200, 0],
            boost: 40,
            distance_to_focus: 1572
          },
          opponent_state: {
            position: [-100, 5000, 17],
            velocity: [300, 50, 0],
            boost: 80,
            distance_to_ball: 1640
          },
          coaching: {
            headline: 'Low-percentage direct shot directly into defender net coverage',
            stance: 'concern',
            confidence: 'hypothesis',
            agreement: 'agree',
            assessment: 'The lone defender was fully stationary in net with 80+ boost. A direct central boomer is the easiest save in Rocket League for an established goalkeeper.',
            feasible_alternatives: [
              {
                id: 'alt-cut-flick',
                action: 'Cut ball left into bounce dribble / flick',
                feasibility: 'feasible',
                feasibility_label: 'Fully Feasible',
                risk_level: 'low',
                pros: 'Forces goalkeeper to step out of net, exposing corners; keeps ball under Blue control.',
                cons: 'Requires 0.8s execution time.',
                description: 'Tap brake, turn slightly left, catch ball on side panel to pop over goalie or into top corner.'
              },
              {
                id: 'alt-infield-pass',
                action: 'Infield pass to trailing teammate',
                feasibility: 'feasible',
                feasibility_label: 'Feasible',
                risk_level: 'medium',
                pros: 'Goalkeeper is focused on focus player; passing opens open-net one-timer.',
                cons: 'Requires precise lateral touch.',
                description: 'Side-flip left to pass ball across midfield to teammate advancing at [-600, 1800].'
              }
            ],
            observed_evidence: [
              {
                id: 'E.goalkeeper.readiness',
                kind: 'observation',
                label: 'Goalkeeper Goal Line Position',
                value: 'Centered in net, 80 boost',
                unit: 'state',
                provenance: 'replay_sample',
                description: 'Goalkeeper had 2.5s of advance notice and is squarely positioned between the posts.'
              },
              {
                id: 'E.shot.target_angle',
                kind: 'derived',
                label: 'Direct Shot Angle to Center Net',
                value: '4 degrees off center line',
                unit: 'degrees',
                provenance: 'derived_geometry',
                description: 'Shot trajectory points directly into the center of the crossbar, requiring zero lateral movement from goalie.'
              }
            ],
            earlier_contributors: [
              {
                id: 'H.1',
                earlier_node: 'N2',
                concerns_node: 'N3',
                question: 'At N2, focus player approached at 1500 uu/s. Did rushing the approach prevent catching the ball for a dribble?',
                evidence_refs: ['N2/E.focus.speed'],
                status: 'hypothesis_unverified',
                not_established: 'Whether defender would have challenged sooner if player slowed down.'
              }
            ],
            takeaway: 'In a 2v1 breakaway against an established goalkeeper, do not boom the ball straight at them. Slow down, cut the ball, or pass to force the keeper to commit first.',
            unknowns: [
              'Whether teammate communicated for a pass.',
              'Goalkeeper reaction latency.'
            ]
          }
        }
      ],
      relations: [
        { from: 'N1', to: 'N2', delta_t_s: 1.5, delta_label: '1.5s approach' },
        { from: 'N2', to: 'N3', delta_t_s: 1.5, delta_label: '1.5s strike setup' }
      ],
      changes: [
        {
          id: 'D.N1-N2.distance_to_goal',
          from_node: 'N1',
          to_node: 'N2',
          field: 'focus.distance_to_goal',
          from_val: 5000,
          to_val: 3200,
          delta: -1800,
          label: 'Advanced 1800 units upfield'
        }
      ],
      timeline_events: [
        { id: 'T.touch.20', t: 31.2, type: 'touch', label: 'Focus player struck ball at 105 km/h' },
        { id: 'T.touch.21', t: 32.4, type: 'touch', label: 'Orange Goalkeeper deflected shot into corner' }
      ],
      retrospective: {
        stage: 2,
        warning: 'HINDSIGHT INFORMATION: Observed after t0 (31.0s). Quarantined by temporal firewall.',
        summary: 'Shot struck directly into goalkeeper at t=32.4s. Goalkeeper made a routine save and cleared downfield; counter-attack fizzled out.',
        events: [
          { t: 31.2, label: 'Direct shot taken' },
          { t: 32.4, label: 'Routine goalie save' },
          { t: 34.0, label: 'Possession turned over' }
        ],
        consequence: 'Wasted 2v1 counter-attack without scoring or forcing a difficult save.'
      }
    }
  ];

  /**
   * Adapter: Convert a live DecisionCase / Tactical Finding from /api/decision-cases
   * into a full EpisodeEvidenceV0 multi-node record if the user uploads a live replay.
   */
  function adaptLiveCaseToEpisode(decisionCase, replay) {
    if (!decisionCase) return null;
    const t0 = decisionCase.t0 || decisionCase.timestamp || 10.0;
    const caseId = decisionCase.case_id || ('case-' + Math.round(t0));
    const focusId = decisionCase.focus_player_id || (replay && replay.players && replay.players[0] && replay.players[0].id) || 'focus';
    const coaching = decisionCase.coaching || {};
    const analysis = decisionCase.analysis || {};
    const evalRes = decisionCase.evaluation || {};

    const n1Time = Math.max(0.5, t0 - 3.2);
    const n2Time = Math.max(n1Time + 0.5, t0 - 1.5);

    return {
      schema: 'EpisodeEvidenceV0',
      episode_id: 'ep-' + caseId,
      title: decisionCase.title || (analysis.situation ? analysis.situation.replace(/_/g, ' ').toUpperCase() : 'Reviewed Tactical Decision'),
      subtitle: (decisionCase.situation || 'Match Episode') + ' · t0 = ' + t0.toFixed(1) + 's',
      player_id: focusId,
      player_name: (replay && replay.players && replay.players.find(p => p.id === focusId)?.name) || 'Selected Player',
      focus_slot: 'focus',
      slots: {
        focus: { team: 'blue', name: 'Selected Player' }
      },
      window: {
        start_s: Math.max(0, t0 - 5.0),
        end_s: t0 + 4.0,
        length_s: 9.0,
        stage1_horizon_s: t0
      },
      nodes: [
        {
          node_id: 'N1',
          label: 'Preceding Setup & Route Initiation',
          t0: n1Time,
          is_primary: false,
          information_cutoff_s: n1Time,
          summary: 'Earlier positioning preceding the commitment moment.',
          coaching: {
            headline: 'Initial positioning leading into engagement',
            stance: 'neutral',
            confidence: 'hypothesis',
            takeaway: 'Observe whether your approach speed and path gave you options.'
          }
        },
        {
          node_id: 'N2',
          label: 'Approach Angle & Tactical Read',
          t0: n2Time,
          is_primary: false,
          information_cutoff_s: n2Time,
          summary: 'Mid-route adjustment as the play developed.',
          coaching: {
            headline: 'Alignment before final commitment',
            stance: 'neutral',
            confidence: 'hypothesis',
            takeaway: 'Check if you recognized opponent priority before commiting.'
          }
        },
        {
          node_id: 'N3',
          label: 'Primary Tactical Commitment (t0)',
          t0: t0,
          is_primary: true,
          information_cutoff_s: t0,
          summary: coaching.display?.headline || analysis.headline || 'Primary reviewed decision moment.',
          coaching: {
            headline: coaching.display?.headline || analysis.headline || 'Reviewed decision moment',
            stance: coaching.display?.stance || 'neutral',
            confidence: coaching.display?.confidence || 'hypothesis',
            agreement: coaching.agreement || 'single_method',
            assessment: analysis.headline || (evalRes.summary || 'Tactical decision evaluated at t0.'),
            feasible_alternatives: (analysis.alternatives || []).map(a => ({
              id: 'alt-' + (a.action || 'action'),
              action: (a.action || '').replace(/_/g, ' '),
              feasibility: a.feasibility || 'feasible',
              feasibility_label: a.feasibility === 'feasible' ? 'Feasible' : 'Constrained',
              risk_level: 'medium',
              pros: 'Tactical alternative observed at t0.',
              cons: 'Trade-off dependent on teammate position.',
              description: a.feasibility_basis || 'Derived from kinematic model at t0.'
            })),
            observed_evidence: (analysis.statements || []).map((s, idx) => ({
              id: 'E.' + idx,
              kind: s.kind || 'observation',
              label: 'Telemetry Observation ' + (idx + 1),
              value: s.text,
              unit: 'evidence',
              provenance: 'replay_analysis',
              description: s.text
            })),
            earlier_contributors: [
              {
                id: 'H.1',
                earlier_node: 'N1',
                concerns_node: 'N3',
                question: 'Did earlier pathing or boost collection influence your positioning here?',
                evidence_refs: ['N1'],
                status: 'hypothesis_unverified',
                not_established: 'No definitive causal claim is made.'
              }
            ],
            takeaway: 'Review your spacing and timing relative to teammate rotation.',
            unknowns: coaching.unknowns || [
              'Camera FOV and perception',
              'Controller analog intent',
              'Teammate voice calls'
            ]
          }
        }
      ],
      relations: [
        { from: 'N1', to: 'N2', delta_t_s: +(n2Time - n1Time).toFixed(1), delta_label: (n2Time - n1Time).toFixed(1) + 's setup' },
        { from: 'N2', to: 'N3', delta_t_s: +(t0 - n2Time).toFixed(1), delta_label: (t0 - n2Time).toFixed(1) + 's commitment' }
      ],
      changes: [
        {
          id: 'D.N1-N3.time',
          from_node: 'N1',
          to_node: 'N3',
          field: 'time_elapsed',
          from_val: n1Time,
          to_val: t0,
          delta: +(t0 - n1Time).toFixed(1),
          label: 'Total episode development: ' + (t0 - n1Time).toFixed(1) + 's'
        }
      ],
      timeline_events: [],
      retrospective: {
        stage: 2,
        warning: 'HINDSIGHT INFORMATION: Quarantined by temporal firewall.',
        summary: 'Observed outcome after t0.',
        events: [],
        consequence: 'Match play continued post-decision.'
      }
    };
  }

  // Export to global scope
  global.ReplayLabCoachingFixtures = {
    FIXTURES: COACHING_FIXTURES,
    adaptLiveCaseToEpisode: adaptLiveCaseToEpisode
  };

})(typeof window !== 'undefined' ? window : this);
