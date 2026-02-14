/**
 * DoubleAgent Service Template - TypeScript/Express
 *
 * Replace TODO comments with your implementation.
 */

import express, { Request, Response } from 'express';

const app = express();
app.use(express.json());

// =============================================================================
// State - Replace with your service's state
// =============================================================================

interface State {
  // TODO: Add your collections here
  // items: Record<number, Item>;
}

let state: State = {
  // TODO: Initialize state
};

const counters: Record<string, number> = {
  // TODO: Add ID counters
  // item_id: 0,
};

function nextId(key: string): number {
  counters[key] = (counters[key] || 0) + 1;
  return counters[key];
}

function resetState(): void {
  state = {
    // TODO: Reset to initial state
  };
  Object.keys(counters).forEach(key => counters[key] = 0);
}

// =============================================================================
// REQUIRED: /_doubleagent endpoints
// =============================================================================

app.get('/_doubleagent/health', (req: Request, res: Response) => {
  res.json({ status: 'healthy' });
});

app.post('/_doubleagent/reset', (req: Request, res: Response) => {
  resetState();
  res.json({ status: 'ok' });
});

app.post('/_doubleagent/seed', (req: Request, res: Response) => {
  const data = req.body || {};
  const seeded: Record<string, number> = {};

  // TODO: Implement seeding for your collections
  // if (data.items) {
  //   for (const item of data.items) {
  //     state.items[item.id] = item;
  //   }
  //   seeded.items = data.items.length;
  // }

  res.json({ status: 'ok', seeded });
});

app.get('/_doubleagent/info', (req: Request, res: Response) => {
  res.json({
    name: 'my-service', // TODO: Change this
    version: '1.0',
  });
});

// =============================================================================
// API Endpoints - Implement your service's API
// =============================================================================

// TODO: Add your API endpoints here
//
// app.get('/items', (req: Request, res: Response) => {
//   res.json(Object.values(state.items));
// });
//
// app.post('/items', (req: Request, res: Response) => {
//   const itemId = nextId('item_id');
//   const item = { id: itemId, ...req.body };
//   state.items[itemId] = item;
//   res.status(201).json(item);
// });

// =============================================================================
// Main
// =============================================================================

const port = parseInt(process.env.PORT || '8080', 10);
app.listen(port, () => {
  console.log(`Service running on port ${port}`);
});
