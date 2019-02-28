const path = require('path');
const webpack = require('webpack');
const CopyWebpackPlugin = require('copy-webpack-plugin'); // copy images over

module.exports = {
  entry: [
    'react-hot-loader/patch',
    'webpack-dev-server/client?http://localhost:8888',
    'webpack/hot/only-dev-server',
    './app/index.js'
  ],
  devtool: 'source-map',
  devServer: {
    hot: true,
    port: 8888,
    publicPath: '/',
    proxy: {
      '/socket.io': {
        target: 'http://localhost:8000',
        // target: 'http://192.168.2.145:8000',
        ws: true,
      },
      '/api': {
        target: 'http://localhost:8000',
        // target: 'http://192.168.2.145:8000',
        secure: false,
        logLevel: 'debug'
      }
    },
    historyApiFallback: true
  },
  output: {
    path: path.resolve(__dirname, 'dev'),
    filename: 'app.js',
    publicPath: '/',
  },
  module: {
    rules: [
      {
        test: /\.scss$/,
        use: [
          {
            loader: 'style-loader',
          },
          {
            loader: 'css-loader',
            options: {
              modules: true,
              localIdentName: '[local]___[hash:base64:5]'
            }
          },
          {
            loader: 'sass-loader'
          }
        ],
        exclude: /node_modules/
      },
      {
        test: /.(png|woff(2)?|eot|ttf|svg)(\?[a-z0-9=\.]+)?$/,
        loader: 'url-loader',
        options: {
          limit: 100000
        }
      },
      {
        test: /\.css$/,
        use: [
          {
            loader: 'style-loader'
          },
          {
            loader: 'css-loader',
            options: {
              modules: true,
              importLoaders: 1,
              localIdentName: '[local]'
            }
          }
        ],
        exclude: /node_modules/
      },
      {
        test: /\.js$/,
        use: [
          {
            loader: 'babel-loader'
          },
        ],
        exclude: /node_modules/
      }
    ]
  },
  plugins: [
    new webpack.DefinePlugin({
      'process.env': {
        'NODE_ENV': JSON.stringify('development'),
        'SOCKET_PATH': JSON.stringify('http://localhost:8888')
      }
    }),
    new webpack.HotModuleReplacementPlugin(),
    new webpack.NamedModulesPlugin(),
    new CopyWebpackPlugin([
      { from: './app/index.html', to: 'index.html' },
      { from: './app/images', to: 'images' },
      { from: './app/fonts', to: 'fonts' }
    ])
  ]
};
