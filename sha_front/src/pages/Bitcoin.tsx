import type { ReactElement, ReactNode } from 'react';
import { repoFile } from '../config';

/**
 * One of the contract's figures. The files are copied from the contract's own directory when
 * the site is built (scripts/sync-data.mjs), so the site and the contract show the same picture.
 */
function Figure({ name, width, height, alt, children }: {
  name: string;
  width: number;
  height: number;
  alt: string;
  children: ReactNode;
}): ReactElement {
  return (
    <figure className="figure">
      <img src={`data/img/bitcoin-mining-v1-${name}.svg`} width={width} height={height} alt={alt} loading="lazy" />
      <figcaption>{children}</figcaption>
    </figure>
  );
}

/** The explanation of the Bitcoin mining problem: what it is for and why it is shaped as it is. */
export function Bitcoin(): ReactElement {
  return (
    <article className="prose">
      <h1>Quantum Bitcoin mining</h1>
      <p className="lede">
        Mining a Bitcoin block is a search by trial and error, and a quantum computer can search in fewer steps.
        This page explains what it would have to run, and why the benchmark's Bitcoin problem is shaped the way
        it is.
      </p>
      <p>
        It is an explanation, not the definition. The technical summary is under{' '}
        <a href="#/rules">The tasks</a>, and the binding text is the{' '}
        <a href={repoFile('sha256_verifier/docs/bitcoin-mining-v1.md')}>contract for bitcoin-mining-v1</a>.
      </p>

      <h2>Mining is a search</h2>
      <p>
        A Bitcoin block starts with an 80-byte header: a version, the hash of the previous block, the merkle
        root (a fingerprint of the block's transactions), a time, the difficulty in a field called{' '}
        <code>bits</code>, and a 4-byte nonce. The block's hash is SHA-256 applied twice to that header.
      </p>
      <p>
        A block is valid only if its hash, read as a number, is not above a target that <code>bits</code>{' '}
        encodes. SHA-256 gives no way to aim, so a miner changes the nonce and hashes again. At today's
        difficulty about one try in 2<sup>79</sup> succeeds.
      </p>
      <p>
        The nonce has only 2<sup>32</sup> values. When they run out, the miner changes a few bytes inside the
        coinbase, the block's first transaction, which pays the miner. That changes the merkle root, so the
        header is new and the nonce can be run through again. Those bytes are usually called the extranonce.
      </p>

      <h2>What a quantum computer changes</h2>
      <p>
        Grover's algorithm finds an input that a circuit marks, among <em>N</em> candidates, by running the
        circuit about √<em>N</em> times when one input is marked, and fewer when more are. The circuit is called
        an oracle. It marks an input by flipping the sign of its amplitude, its phase, and must leave nothing
        else behind.
      </p>
      <p>
        For mining, the candidates are the values of the extranonce and the nonce, and the oracle marks those
        that give a block whose hash meets the target. Where a classical miner needs about 2<sup>79</sup> tries,
        Grover's algorithm needs in the order of 2<sup>40</sup> runs of the oracle.
      </p>
      <p>
        Those runs come one after another, with a small reflection on the search register between them, so the
        cost of mining is very nearly the cost of one run of the oracle times their number. This benchmark
        measures the first factor: how few qubits and how few Toffoli gates one run can take. It does not say
        whether a quantum miner would beat classical ones. That depends on the hardware.
      </p>
      <p>
        The hardware would have to be very fast. Bitcoin's miners together find a block about every ten
        minutes, and a search that is still running when someone else finds one has to start again on the next
        block. So a single quantum computer has about ten minutes for its 2<sup>40</sup> runs:{' '}
        <strong>about half a nanosecond for each run of the oracle</strong>. That is far beyond any quantum
        hardware proposed so far, which needs much longer than that for a single Toffoli gate, and the oracle
        is hundreds of thousands of them.
      </p>
      <p>
        More computers help little. Classical mining is parallel: <em>k</em> miners find a block <em>k</em>{' '}
        times sooner than one. Quantum mining is embarrassingly not parallel: <em>k</em> quantum computers
        that share out the search finish only √<em>k</em> times sooner than one.
      </p>

      <h2>What the oracle computes</h2>
      <p>
        The search register is 80 qubits: 6 bytes of the coinbase and the 4-byte nonce. Everything else in the
        block stays fixed during one search and is known in advance, so it enters as classical bits. From these
        the oracle works its way to the block hash in five SHA-256 compressions:
      </p>
      <ol>
        <li>
          The end of the coinbase, which holds the 6 searched bytes, is compressed from a midstate: the SHA-256
          state after the earlier part of the coinbase. That part does not change during a search, so it is
          hashed beforehand, classically.
        </li>
        <li>
          The result is hashed again. A transaction's id is its double SHA-256, and with one transaction in the
          block that id is also the merkle root.
        </li>
        <li>
          The header's first 64 bytes are compressed. They hold the version, the previous block's hash and
          most of the merkle root.
        </li>
        <li>
          The header's last 16 bytes are compressed: the rest of the merkle root, the time, <code>bits</code>{' '}
          and the searched nonce.
        </li>
        <li>The result is hashed again, which gives the block hash.</li>
      </ol>
      <p>
        The hash is then compared with the target and the phase is flipped if it is below. After that every
        intermediate value has to be uncomputed, because scratch qubits must end at zero.
      </p>
      <Figure name="oracle" width={680} height={676}
        alt="The five compressions: the coinbase's last block from the midstate, its second hash giving the merkle root, the header's two blocks, and the header's second hash giving the block hash, which is masked and compared to the target.">
        The five compressions. Each box on the left of a compression is part of its 64-byte block, in order
        from the top; the arrow from above is the state it starts from.
      </Figure>
      <Figure name="header" width={680} height={420}
        alt="The 80-byte header over two 64-byte SHA-256 blocks: version, prev_hash and 28 bytes of the merkle root in the first; the root's last 4 bytes, time, bits, nonce and 48 bytes of padding in the second.">
        Where the header's fields fall in the two blocks SHA-256 splits it into. The merkle root, which depends
        on the search register, reaches into both.
      </Figure>

      <h2>Why the problem is shaped this way</h2>

      <h3>The coinbase is inside the oracle</h3>
      <p>
        Grover's algorithm needs the whole haystack in one quantum register. The nonce alone is 32 qubits:
        2<sup>32</sup> candidates, when a hit comes once in 2<sup>79</sup>. Searching the nonce with Grover's
        algorithm and the extranonce with a classical loop around it would give most of the speedup away. So
        the register reaches 48 qubits into the coinbase, for 2<sup>80</sup> candidates, enough to expect about
        two hits at today's difficulty. Changing the coinbase changes the merkle root, so the oracle has to
        compute the merkle root too.
      </p>

      <h3>The block holds only the coinbase</h3>
      <p>
        In a usual block the transactions are hashed in pairs, level by level, down to the merkle root, and a
        change to the coinbase has to be carried down every level. Each level would add more hashing to the
        oracle. A block whose only transaction is the coinbase has no tree: its merkle root is the coinbase's
        double SHA-256. Such blocks are valid and miners do produce them, which is why there are real ones to
        test on.
      </p>
      <Figure name="merkle-root" width={680} height={322}
        alt="In a usual block the transactions are hashed pairwise down to the merkle root. In a coinbase-only block the merkle root is the double SHA-256 of the coinbase.">
        The merkle root of a usual block, and of a block that holds only its coinbase.
      </Figure>

      <h3>The answer is a phase</h3>
      <p>
        Grover's algorithm calls an oracle that flips the phase of the inputs it marks. A circuit that wrote
        its answer into a qubit would have to be wrapped to get that. The benchmark asks for the oracle the
        algorithm actually calls, so there is no output register, and the search register must come back
        unchanged.
      </p>

      <h3>Real blocks are in the tests</h3>
      <p>
        Sixteen blocks of Bitcoin's main network that hold only a coinbase are built into the verifier, from
        the difficulty of 2009 to that of today. A circuit must flip the phase for each of them as mined, and
        must not when the nonce is one higher or any one searched bit is flipped. So every circuit on the
        leaderboard accepts real Bitcoin blocks.
      </p>
      <p>
        That is a statement about the oracle, not about how those blocks were mined. The 6 bytes the oracle
        searches are whatever the coinbase has at that position, not the bytes the block's miner varied.
      </p>

      <h3>The mask</h3>
      <p>
        Real blocks are not enough. At today's difficulty a hit costs about 2<sup>79</sup> hashes to find, so
        the only hits anyone has are the mined blocks, and those are public: a circuit could recognise them
        without hashing anything. A test also needs near misses, such as a hash that would meet the target but
        for one bit, or one that lands exactly on it. Nobody can produce those either.
      </p>
      <p>
        The mask is the answer to both. It is 96 classical bits that are XORed into the 96 most significant
        bits of the hash before the comparison. The verifier takes any random input, computes its hash, and
        picks the mask that puts the compared value where it wants: just under the target, exactly on it, or
        under it but for one bit. With a mask of zero the oracle is Bitcoin's own check.
      </p>
      <p>
        The mask costs a circuit no Toffolis, since XOR with a classical bit is an X gate under a condition.
        It also tells the circuit nothing: it is the wanted value XORed with a hash that the circuit does not
        know until it has computed it.
      </p>

      <h3>Below the target, not on it</h3>
      <p>
        Bitcoin accepts a hash equal to the target; the oracle requires it to be below. The two rules differ on
        one value of the hash, which no test can reach. With the strict rule the answer depends only on the
        bits of the hash from the target's mantissa upwards, and at every supported difficulty those lie within
        the 96 bits the mask covers.
      </p>

      <h3>Ten difficulties</h3>
      <p>
        The exponent of the target may take ten values. Seven are those Bitcoin's main network has used, from
        2009 to today, and three are easier than any real block. The random tests use the ten equally often. A
        circuit may read the exponent, and at an easy one it needs less of the hash, so the Toffoli count of a
        circuit that takes this shortcut is its average over the ten, not its cost at today's difficulty.
      </p>

      <h3>Only the proof of work</h3>
      <p>
        The oracle checks the hash against the target and nothing else. Whether the coinbase is a valid
        transaction, and every other rule a block must meet, is outside it.
      </p>

      <h2>Quantum mining would break Bitcoin</h2>
      <p>
        To keep the oracle small, the block it mines holds no transaction but the coinbase. A quantum miner
        running it would produce blocks that confirm nothing, and if every block were mined that way, Bitcoin's
        transactions would stop.
      </p>
      <p>
        That is where quantum mining would settle. When two quantum miners race for the same block, the one
        that finishes first takes the reward. A miner that includes transactions has a merkle tree to hash, so
        each run of its oracle takes longer. On the same hardware it finishes second, and the empty block wins.
      </p>
      <p>
        The chain would also fork more often. A quantum miner does not have to fix the length of its search in
        advance: when a rival's block arrives it can stop and measure, with some chance of holding a valid
        block of its own. If every quantum miner does that, several blocks appear at about the same moment, as
        Or Sattath argues in{' '}
        <a href="https://arxiv.org/abs/1804.08118">On the insecurity of quantum Bitcoin mining</a>.
      </p>

      <h2>What passing does not show</h2>
      <p>
        At today's difficulty the oracle with a mask of zero is tested on the real blocks alone, because nobody
        can make another input that hits. A circuit could treat a zero mask differently. It would gain nothing,
        since it must still pass the masked tests and is scored on them, but no test can rule it out. What the
        tests do bound is under <a href="#/verification">Verification</a>.
      </p>

      <h2>Where the leaderboard starts</h2>
      <p>
        The baseline on the <a href="#/">leaderboard</a> does it the plain way: five compressions built like
        the SHA-256 compression baseline, the comparison, and then everything backwards to clear the scratch.
        The circuits on the SHA-256 compression leaderboard are the natural place to look for savings.
      </p>
    </article>
  );
}
