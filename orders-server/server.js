// orders_server/server.js
const express = require('express');
const fs = require('fs');
const path = require('path');
const cors = require('cors');

const app = express();
const PORT = 8000;

// FIX: Handle Windows paths and project structure
// Look for orders folder in multiple locations
let ORDERS_DIR = null;

const possiblePaths = [
  path.join(__dirname, '..', 'backend', 'orders'),
  path.join(__dirname, '..', '..', 'backend', 'orders'),
  path.resolve(process.cwd(), 'backend', 'orders'),
  path.resolve(process.cwd(), 'orders'),
];

for (let dir of possiblePaths) {
  if (fs.existsSync(dir)) {
    ORDERS_DIR = dir;
    console.log(`✅ Found orders directory: ${ORDERS_DIR}`);
    break;
  }
}

// If not found, create it in the most likely location
if (!ORDERS_DIR) {
  ORDERS_DIR = path.join(__dirname, '..', 'backend', 'orders');
  console.log(`📁 Creating orders directory: ${ORDERS_DIR}`);
  fs.mkdirSync(ORDERS_DIR, { recursive: true });
}

console.log('\n' + '='.repeat(70));
console.log('☕ Orders Server Starting...');
console.log('='.repeat(70));
console.log(`📁 Orders Directory: ${ORDERS_DIR}`);
console.log('='.repeat(70) + '\n');

// Middleware
app.use(cors({
  origin: '*',
  methods: ['GET', 'POST', 'DELETE'],
  credentials: true
}));
app.use(express.json());
app.use(express.static('public'));

// ============= API ENDPOINTS =============

// Get all orders
app.get('/api/orders', (req, res) => {
  try {
    if (!fs.existsSync(ORDERS_DIR)) {
      console.log('⚠️ Orders directory does not exist');
      return res.json({ success: true, orders: [], count: 0 });
    }

    const files = fs.readdirSync(ORDERS_DIR).filter(f => 
      f.startsWith('order_') && f.endsWith('.json')
    );

    console.log(`📊 Found ${files.length} order files`);

    const orders = files.map(file => {
      try {
        const filePath = path.join(ORDERS_DIR, file);
        const content = fs.readFileSync(filePath, 'utf8');
        return JSON.parse(content);
      } catch (err) {
        console.error(`❌ Error reading ${file}:`, err.message);
        return null;
      }
    }).filter(order => order !== null);

    console.log(`✅ Returning ${orders.length} orders to dashboard`);
    res.json({ 
      success: true, 
      orders: orders,
      count: orders.length,
      directory: ORDERS_DIR 
    });
  } catch (error) {
    console.error('❌ Error reading orders:', error.message);
    res.status(500).json({ 
      success: false, 
      error: error.message,
      directory: ORDERS_DIR 
    });
  }
});

// Get order by ID
app.get('/api/orders/:id', (req, res) => {
  try {
    const file = path.join(ORDERS_DIR, `order_${req.params.id}.json`);
    if (fs.existsSync(file)) {
      const content = fs.readFileSync(file, 'utf8');
      res.json({ success: true, order: JSON.parse(content) });
    } else {
      res.status(404).json({ success: false, error: 'Order not found' });
    }
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

// Get statistics
app.get('/api/stats', (req, res) => {
  try {
    if (!fs.existsSync(ORDERS_DIR)) {
      return res.json({
        success: true,
        stats: {
          totalOrders: 0,
          drinks: {},
          sizes: {},
          milks: {},
          extras: {}
        }
      });
    }

    const files = fs.readdirSync(ORDERS_DIR).filter(f => 
      f.startsWith('order_') && f.endsWith('.json')
    );
    
    let stats = {
      totalOrders: files.length,
      drinks: {},
      sizes: {},
      milks: {},
      extras: {}
    };

    files.forEach(file => {
      try {
        const filePath = path.join(ORDERS_DIR, file);
        const content = fs.readFileSync(filePath, 'utf8');
        const data = JSON.parse(content).order;

        if (data.drinkType) stats.drinks[data.drinkType] = (stats.drinks[data.drinkType] || 0) + 1;
        if (data.size) stats.sizes[data.size] = (stats.sizes[data.size] || 0) + 1;
        if (data.milk) stats.milks[data.milk] = (stats.milks[data.milk] || 0) + 1;
        if (data.extras && Array.isArray(data.extras)) {
          data.extras.forEach(extra => {
            stats.extras[extra] = (stats.extras[extra] || 0) + 1;
          });
        }
      } catch (err) {
        console.error(`Error processing ${file}:`, err.message);
      }
    });

    res.json({ success: true, stats });
  } catch (error) {
    console.error('Error calculating stats:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// Health check
app.get('/health', (req, res) => {
  const ordersExist = fs.existsSync(ORDERS_DIR);
  let orderCount = 0;
  
  try {
    if (ordersExist) {
      orderCount = fs.readdirSync(ORDERS_DIR)
        .filter(f => f.startsWith('order_') && f.endsWith('.json')).length;
    }
  } catch (e) {
    console.error('Error counting orders:', e.message);
  }
  
  res.json({ 
    success: true, 
    message: 'Orders Server is running',
    ordersDir: ORDERS_DIR,
    exists: ordersExist,
    orderCount: orderCount,
    timestamp: new Date().toISOString()
  });
});

// Serve dashboard
app.get('/', (req, res) => {
  res.sendFile(path.join(__dirname, 'dashboard.html'));
});

// 404 handler
app.use((req, res) => {
  res.status(404).json({ success: false, error: 'Not found' });
});

// Error handler
app.use((err, req, res, next) => {
  console.error('Server error:', err);
  res.status(500).json({ success: false, error: 'Internal server error' });
});

// Start server
const server = app.listen(PORT, () => {
  console.log(`\n☕ Orders Server running on http://localhost:${PORT}`);
  console.log(`Dashboard: http://localhost:${PORT}`);
  console.log(`API: http://localhost:${PORT}/api/orders`);
  console.log(`Health: http://localhost:${PORT}/health`);
  console.log(`📁 Reading orders from: ${ORDERS_DIR}\n`);
});

// Handle graceful shutdown
process.on('SIGINT', () => {
  console.log('\n✋ Server shutting down...');
  server.close(() => {
    process.exit(0);
  });
});